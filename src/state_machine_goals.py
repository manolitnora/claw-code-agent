"""Goal + Task lifecycle persistence for the state machine.

Step 5.9 of the runway in ``~/.latti/STATE_MACHINE.md``: typed Goal and Task
schemas exist in agent_state_machine.py, but no code today constructs or
persists them. This module fills that gap.

Storage: JSONL append-only files in a directory passed at construction.
- ``goals.jsonl`` — one Goal per line, append-only (no in-place edits)
- ``tasks.jsonl`` — one Task per line, append-only; status transitions are
  expressed as new lines whose ``id`` matches an earlier line. The latest
  line for a given task id wins.

Append-only storage means concurrent writers don't corrupt each other and
the full history is recoverable. The "current view" is materialized by
folding the lines.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from src.agent_state_machine import Goal, Task, TaskStatus


class GoalRegistry:
    """Append-only Goal storage."""

    def __init__(self, storage_dir: Path | str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._goals_path = self._dir / 'goals.jsonl'

    @property
    def goals_path(self) -> Path:
        return self._goals_path

    def register(self, goal: Goal) -> Goal:
        """Append the Goal to the journal. Returns it unchanged for chaining."""
        with self._goals_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(goal.to_dict()) + '\n')
        return goal

    def list_all(self) -> list[Goal]:
        """Return every Goal ever registered, in registration order."""
        if not self._goals_path.exists():
            return []
        out: list[Goal] = []
        for line in self._goals_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(Goal(
                id=d['id'], title=d['title'],
                success_criteria=tuple(d.get('success_criteria', [])),
                created_at=d.get('created_at', 0.0),
                owner=d.get('owner', 'user'),
                parent_goal=d.get('parent_goal'),
            ))
        return out

    def get(self, goal_id: str) -> Goal | None:
        for g in self.list_all():
            if g.id == goal_id:
                return g
        return None

    def children_of(self, parent_id: str) -> list[Goal]:
        return [g for g in self.list_all() if g.parent_goal == parent_id]


class TaskTracker:
    """Append-only Task storage with status-fold materialization.

    A Task's "current state" is the LATEST line in tasks.jsonl whose id matches.
    Earlier lines remain on disk as audit history.
    """

    def __init__(self, storage_dir: Path | str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._tasks_path = self._dir / 'tasks.jsonl'

    @property
    def tasks_path(self) -> Path:
        return self._tasks_path

    def add(self, task: Task) -> Task:
        return self._append(task)

    def update_status(self, task_id: str, status: TaskStatus,
                      completed_at: float | None = None) -> Task | None:
        """Append a new line with the updated status. Returns the new Task or None."""
        current = self.get(task_id)
        if current is None:
            return None
        new = Task(
            id=current.id, goal_id=current.goal_id, description=current.description,
            parent_task=current.parent_task, status=status,
            created_at=current.created_at,
            completed_at=completed_at if completed_at is not None else current.completed_at,
        )
        return self._append(new)

    def _append(self, task: Task) -> Task:
        with self._tasks_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(task.to_dict()) + '\n')
        return task

    def _fold(self) -> dict[str, Task]:
        """Read all lines, return latest-per-id."""
        if not self._tasks_path.exists():
            return {}
        out: dict[str, Task] = {}
        for line in self._tasks_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[d['id']] = Task(
                id=d['id'], goal_id=d['goal_id'], description=d['description'],
                parent_task=d.get('parent_task'),
                status=d.get('status', 'pending'),
                created_at=d.get('created_at', 0.0),
                completed_at=d.get('completed_at'),
            )
        return out

    def get(self, task_id: str) -> Task | None:
        return self._fold().get(task_id)

    def list_for_goal(self, goal_id: str) -> list[Task]:
        return [t for t in self._fold().values() if t.goal_id == goal_id]

    def list_active_for_goal(self, goal_id: str) -> list[Task]:
        return [
            t for t in self._fold().values()
            if t.goal_id == goal_id and t.status in ('pending', 'in_progress', 'blocked')
        ]

    def history(self, task_id: str) -> list[Task]:
        """Return every line ever written for this task id, in order."""
        if not self._tasks_path.exists():
            return []
        out: list[Task] = []
        for line in self._tasks_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get('id') == task_id:
                out.append(Task(
                    id=d['id'], goal_id=d['goal_id'], description=d['description'],
                    parent_task=d.get('parent_task'),
                    status=d.get('status', 'pending'),
                    created_at=d.get('created_at', 0.0),
                    completed_at=d.get('completed_at'),
                ))
        return out
