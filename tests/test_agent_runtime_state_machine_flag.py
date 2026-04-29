"""Tests for the LATTI_USE_STATE_MACHINE flag-gated dispatch.

Step 2b of the runway in ``~/.latti/STATE_MACHINE.md``: a real chat-turn-style
tool call is routed through StateMachineRunner only when the flag is set.
Default-off must be a no-op (no _sm_runner constructed, existing path runs).
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent_runtime import LocalCodingAgent
from src.agent_state_machine import State
from src.agent_tools import build_tool_context, default_tool_registry
from src.agent_types import (
    AgentPermissions,
    AgentRuntimeConfig,
    ModelConfig,
    ModelPricing,
    ToolExecutionResult,
)
from src.state_machine_runner import StateMachineRunner


def _make_agent(tmp_path: Path) -> LocalCodingAgent:
    runtime_config = AgentRuntimeConfig(
        cwd=tmp_path,
        permissions=AgentPermissions(
            allow_file_write=True, allow_shell_commands=False,
        ),
    )
    model_config = ModelConfig(
        model='gpt-4o-mini',
        api_key='test-key',
        base_url='http://localhost:0/unused',
        pricing=ModelPricing(),
    )
    return LocalCodingAgent(
        model_config=model_config,
        runtime_config=runtime_config,
    )


class _ToolCallStub:
    """Minimal duck-typed stand-in for the agent's internal tool_call object."""

    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = arguments
        self.id = f'tc_{name}'


def test_flag_off_does_not_construct_state_machine_runner(tmp_path):
    """Default is opt-in (after 02:22 revert from Step 6 default-on).
    With no env var set, __post_init__ doesn't construct the runner."""
    os.environ.pop('LATTI_USE_STATE_MACHINE', None)
    agent = _make_agent(tmp_path)
    assert agent._sm_runner is None
    assert agent._sm_state is None


def test_flag_on_dispatch_executes_real_read_file(tmp_path, monkeypatch):
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')
    target = tmp_path / 'flag_test.txt'
    target.write_text('hello from flag-on path', encoding='utf-8')

    agent = _make_agent(tmp_path)
    tc = _ToolCallStub('read_file', {'path': 'flag_test.txt'})
    result = agent._dispatch_via_state_machine(tc)

    assert isinstance(result, ToolExecutionResult)
    assert result.ok is True
    assert result.name == 'read_file'
    assert 'hello from flag-on path' in result.content
    # Lazy construction happened
    assert agent._sm_runner is not None
    assert isinstance(agent._sm_runner, StateMachineRunner)
    assert agent._sm_state is not None


def test_flag_on_dispatch_advances_state_across_calls(tmp_path, monkeypatch):
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')
    f1 = tmp_path / 'a.txt'
    f1.write_text('A', encoding='utf-8')
    f2 = tmp_path / 'b.txt'
    f2.write_text('B', encoding='utf-8')

    agent = _make_agent(tmp_path)
    agent._dispatch_via_state_machine(_ToolCallStub('read_file', {'path': 'a.txt'}))
    state_after_first = agent._sm_state
    agent._dispatch_via_state_machine(_ToolCallStub('read_file', {'path': 'b.txt'}))
    state_after_second = agent._sm_state

    assert state_after_first is not None
    assert state_after_second is not None
    assert state_after_first.turn_id != state_after_second.turn_id


def test_flag_on_unknown_tool_returns_error_result(tmp_path, monkeypatch):
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')
    agent = _make_agent(tmp_path)
    result = agent._dispatch_via_state_machine(_ToolCallStub('totally_made_up_tool', {}))

    assert isinstance(result, ToolExecutionResult)
    assert result.ok is False
    # Loop did not crash — graceful error result was returned


def test_flag_on_runner_has_validators_and_evaluators_wired(tmp_path, monkeypatch):
    """The auto-constructed runner in agent_runtime should ship with the
    default validators (shape, non-empty-content) and evaluators (budget)
    so flag-on dispatches get real validation + scoring, not bare execution."""
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')
    target = tmp_path / 'wiring.txt'
    target.write_text('content', encoding='utf-8')
    agent = _make_agent(tmp_path)
    agent._dispatch_via_state_machine(_ToolCallStub('read_file', {'path': 'wiring.txt'}))

    runner = agent._sm_runner
    assert runner is not None
    # Validators wired
    validator_names = {v.name for v in runner._validators}
    assert 'observation_shape' in validator_names
    assert 'non_empty_content' in validator_names
    # Evaluators wired
    evaluator_names = {type(e).__name__ for e in runner._evaluators}
    assert 'BudgetExhaustionEvaluator' in evaluator_names


def test_flag_on_validator_blocks_dispatch_with_misshapen_observation(tmp_path, monkeypatch):
    """A misbehaving operator that returns the wrong action_id should be
    caught by ObservationShapeValidator and surface as ok=False."""
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')

    from src.agent_state_machine import Observation
    from src.state_machine_runner import StateMachineRunner
    from src.state_machine_validators import ObservationShapeValidator

    class MisidentifyingOp:
        @property
        def kind(self):
            return 'tool_call'

        def can_handle(self, action):
            return action.kind == 'tool_call'

        def execute(self, action, state):
            return Observation(action_id='wrong_id', kind='success',
                               payload={'content': 'x', 'ok': True, 'tool_name': 'read_file'})

    agent = _make_agent(tmp_path)
    # Pre-inject a runner with the misbehaving operator + the real validator
    agent._sm_runner = StateMachineRunner(
        operators=[MisidentifyingOp()],
        decision_log_path=tmp_path / 'log.jsonl',
        validators=[ObservationShapeValidator()],
    )

    result = agent._dispatch_via_state_machine(_ToolCallStub('read_file', {'path': 'x'}))
    # Validator blocked → result.ok is False
    assert result.ok is False


def test_flag_on_logs_policy_decision_when_runner_preinjected(tmp_path, monkeypatch):
    """Pre-inject a runner with a temp log path and verify logging works.

    Default-arg binding for ``decision_log_path`` happens at function-definition
    time, so monkeypatching ``DEFAULT_DECISION_LOG`` on the module doesn't
    redirect a runner constructed lazily inside the agent. Pre-injection is the
    deterministic way to assert log-write behavior in test scope.
    """
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')
    log_path = tmp_path / 'pdlog.jsonl'

    target = tmp_path / 'logged.txt'
    target.write_text('content', encoding='utf-8')
    agent = _make_agent(tmp_path)

    # Pre-construct a runner with the temp log path and inject it.
    from src.state_machine_operators import ToolCallOperator
    agent._sm_runner = StateMachineRunner(
        operators=[ToolCallOperator(agent.tool_registry, agent.tool_context)],
        decision_log_path=log_path,
    )

    agent._dispatch_via_state_machine(_ToolCallStub('read_file', {'path': 'logged.txt'}))

    assert log_path.exists()
    content = log_path.read_text().strip()
    assert content  # at least one line
    import json
    rec = json.loads(content.splitlines()[0])
    assert rec['decision']['chose']['payload']['tool_name'] == 'read_file'
    assert rec['observation_kind'] == 'success'
