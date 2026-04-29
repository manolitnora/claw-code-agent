"""Tests that agent_runtime exposes typed memory/goals/tasks surfaces."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_runtime import LocalCodingAgent
from src.agent_state_machine import Goal, MemoryRecord, Task
from src.agent_types import (
    AgentPermissions, AgentRuntimeConfig, ModelConfig, ModelPricing,
)
from src.state_machine_goals import GoalRegistry, TaskTracker
from src.state_machine_memory import LattiMemoryStore


def _make_agent(tmp_path):
    return LocalCodingAgent(
        model_config=ModelConfig(
            model='unused', api_key='x', base_url='http://0/',
            pricing=ModelPricing(),
        ),
        runtime_config=AgentRuntimeConfig(
            cwd=tmp_path,
            permissions=AgentPermissions(allow_file_write=True, allow_shell_commands=False),
        ),
    )


def test_state_machine_memory_returns_store(tmp_path):
    agent = _make_agent(tmp_path)
    store = agent.state_machine_memory()
    # Even if ~/.latti is missing, the store can be constructed (creates dir)
    assert isinstance(store, LattiMemoryStore)


def test_state_machine_memory_is_cached(tmp_path):
    agent = _make_agent(tmp_path)
    a = agent.state_machine_memory()
    b = agent.state_machine_memory()
    assert a is b


def test_state_machine_goals_returns_registry(tmp_path):
    agent = _make_agent(tmp_path)
    reg = agent.state_machine_goals()
    assert isinstance(reg, GoalRegistry)


def test_state_machine_tasks_returns_tracker(tmp_path):
    agent = _make_agent(tmp_path)
    tracker = agent.state_machine_tasks()
    assert isinstance(tracker, TaskTracker)


def test_lazy_construction_does_not_fire_at_init(tmp_path):
    agent = _make_agent(tmp_path)
    # Direct field check: nothing constructed yet
    assert agent._sm_memory is None
    assert agent._sm_goals is None
    assert agent._sm_tasks is None
