from __future__ import annotations

from pathlib import Path

from src.agent_types import AgentRunResult, UsageStats
from src.background_runtime import BackgroundSessionRecord
from src.tui_supervisor import (
    load_worker_result,
    run_background_turn,
    save_worker_result,
)


class _FakeRuntime:
    def __init__(self, root: Path, records: list[BackgroundSessionRecord]) -> None:
        self.root = root
        self._records = list(records)

    def load_record(self, background_id: str) -> BackgroundSessionRecord:
        assert self._records
        return self._records.pop(0)


def _record(
    background_id: str,
    *,
    status: str,
    session_id: str | None = None,
    session_path: str | None = None,
    stop_reason: str | None = None,
) -> BackgroundSessionRecord:
    return BackgroundSessionRecord(
        background_id=background_id,
        pid=123,
        prompt='prompt',
        workspace_cwd='/tmp',
        model='gpt-4o-mini',
        mode='agent',
        status=status,
        log_path='/tmp/log.txt',
        record_path='/tmp/record.json',
        started_at='2026-04-29T00:00:00+00:00',
        command=('python3', '-m', 'src.main'),
        finished_at='2026-04-29T00:00:01+00:00' if status != 'running' else None,
        exit_code=0 if status == 'completed' else 1 if status == 'failed' else None,
        stop_reason=stop_reason,
        session_id=session_id,
        session_path=session_path,
    )


def test_worker_result_round_trip(tmp_path: Path) -> None:
    result = AgentRunResult(
        final_output='hello from worker',
        turns=2,
        tool_calls=1,
        transcript=({'role': 'assistant', 'content': 'hello from worker'},),
        events=({'type': 'tool_result'},),
        usage=UsageStats(input_tokens=5, output_tokens=2),
        total_cost_usd=0.12,
        stop_reason='stop',
        file_history=({'action': 'read_file'},),
        session_id='sess_123',
        session_path='/tmp/sess_123.json',
        scratchpad_directory='/tmp/scratch',
    )

    save_worker_result(tmp_path, 'bg_123', result)
    loaded = load_worker_result(tmp_path, 'bg_123')

    assert loaded == result


def test_run_background_turn_returns_loaded_result_when_worker_completes(tmp_path: Path) -> None:
    result = AgentRunResult(
        final_output='completed turn',
        turns=1,
        tool_calls=0,
        transcript=(),
        usage=UsageStats(input_tokens=3, output_tokens=1),
        session_id='sess_abc',
        session_path='/tmp/sess_abc.json',
    )
    save_worker_result(tmp_path, 'bg_ok', result)
    runtime = _FakeRuntime(
        tmp_path,
        [
            _record('bg_ok', status='running'),
            _record(
                'bg_ok',
                status='completed',
                session_id='sess_abc',
                session_path='/tmp/sess_abc.json',
                stop_reason='completed',
            ),
        ],
    )

    final_record, loaded = run_background_turn(
        runtime,
        launch_worker=lambda: _record('bg_ok', status='running'),
        poll_interval_seconds=0.0,
    )

    assert final_record.status == 'completed'
    assert loaded.final_output == 'completed turn'
    assert loaded.session_id == 'sess_abc'

