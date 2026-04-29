from __future__ import annotations

import json
from pathlib import Path

from src.agent_runtime import LocalCodingAgent
from src.agent_types import (
    AgentPermissions,
    AgentRuntimeConfig,
    AssistantTurn,
    ModelConfig,
    ModelPricing,
    ToolCall,
    UsageStats,
)
from src.state_machine_evaluators import BudgetExhaustionEvaluator
from src.state_machine_operators import (
    DelegateAgentOperator,
    RealLLMOperator,
    ToolCallOperator,
)
from src.state_machine_runner import StateMachineRunner
from src.state_machine_validators import (
    NonEmptyContentValidator,
    ObservationShapeValidator,
)


def _make_agent(tmp_path: Path) -> LocalCodingAgent:
    return LocalCodingAgent(
        model_config=ModelConfig(
            model='gpt-4o-mini',
            api_key='test-key',
            base_url='http://localhost:0/unused',
            pricing=ModelPricing(),
        ),
        runtime_config=AgentRuntimeConfig(
            cwd=tmp_path,
            permissions=AgentPermissions(
                allow_file_write=True,
                allow_shell_commands=False,
            ),
        ),
    )


def _inject_runner(agent: LocalCodingAgent, log_path: Path) -> None:
    agent._sm_runner = StateMachineRunner(
        operators=[
            RealLLMOperator(agent.client),
            DelegateAgentOperator(agent._execute_delegate_agent),
            ToolCallOperator(agent.tool_registry, agent.tool_context),
        ],
        decision_log_path=log_path,
        validators=[
            ObservationShapeValidator(),
            NonEmptyContentValidator(),
        ],
        evaluators=[BudgetExhaustionEvaluator()],
    )


def _read_rationales(log_path: Path) -> list[str]:
    return [
        json.loads(line)['decision']['rationale']
        for line in log_path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]


def test_flag_on_outer_loop_logs_runtime_controller_rationale_for_plain_answer(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')
    agent = _make_agent(tmp_path)
    _inject_runner(agent, tmp_path / 'loop_plain.jsonl')
    monkeypatch.setattr(agent, '_check_rotation_gate', lambda result: None)

    def fake_complete(messages, tools, *, output_schema=None, model_override=None):
        return AssistantTurn(
            content='typed hello',
            finish_reason='stop',
            usage=UsageStats(input_tokens=4, output_tokens=2),
        )

    monkeypatch.setattr(agent.client, 'complete', fake_complete)

    result = agent.run('say hello')

    assert result.final_output == 'typed hello'
    assert _read_rationales(tmp_path / 'loop_plain.jsonl') == [
        'rule_fired: runtime_query_model',
    ]


def test_flag_on_outer_loop_logs_runtime_controller_rationale_for_tool_turn(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')
    agent = _make_agent(tmp_path)
    _inject_runner(agent, tmp_path / 'loop_tool.jsonl')
    monkeypatch.setattr(agent, '_check_rotation_gate', lambda result: None)
    (tmp_path / 'note.txt').write_text('tool note', encoding='utf-8')

    turns = iter(
        [
            AssistantTurn(
                content='need a tool',
                tool_calls=(
                    ToolCall(id='call_1', name='read_file', arguments={'path': 'note.txt'}),
                ),
                finish_reason='tool_calls',
                usage=UsageStats(input_tokens=6, output_tokens=3),
            ),
            AssistantTurn(
                content='done after tool',
                finish_reason='stop',
                usage=UsageStats(input_tokens=5, output_tokens=2),
            ),
        ]
    )

    monkeypatch.setattr(
        agent.client,
        'complete',
        lambda messages, tools, *, output_schema=None, model_override=None: next(turns),
    )

    result = agent.run('read the file')

    assert result.final_output == 'done after tool'
    assert _read_rationales(tmp_path / 'loop_tool.jsonl') == [
        'rule_fired: runtime_query_model',
        'rule_fired: runtime_execute_pending_tool_call',
        'rule_fired: runtime_query_model',
    ]


def test_flag_on_outer_loop_logs_runtime_controller_rationale_for_continuation(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv('LATTI_USE_STATE_MACHINE', '1')
    agent = _make_agent(tmp_path)
    _inject_runner(agent, tmp_path / 'loop_continue.jsonl')
    monkeypatch.setattr(agent, '_check_rotation_gate', lambda result: None)

    turns = iter(
        [
            AssistantTurn(
                content='part one ',
                finish_reason='length',
                usage=UsageStats(input_tokens=6, output_tokens=3),
            ),
            AssistantTurn(
                content='part two',
                finish_reason='stop',
                usage=UsageStats(input_tokens=5, output_tokens=2),
            ),
        ]
    )

    monkeypatch.setattr(
        agent.client,
        'complete',
        lambda messages, tools, *, output_schema=None, model_override=None: next(turns),
    )

    result = agent.run('continue if needed')

    assert result.final_output == 'part one part two'
    assert _read_rationales(tmp_path / 'loop_continue.jsonl') == [
        'rule_fired: runtime_query_model',
        'rule_fired: runtime_query_model',
    ]
