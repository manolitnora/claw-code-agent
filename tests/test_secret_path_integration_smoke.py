"""End-to-end smoke: ReadFileOperator → session → llm_call wall check.

This is the integration substitute for live Latti verification. It uses the
actual operator (no mocks), the actual session methods, and the actual wall
function. If Latti's wedge can recur, this test catches it.

Two scenarios:
  1. Read of a `.env`-named file → operator refuses, no secret enters
     session, no wall fires on subsequent llm_call.
  2. Read of a non-secret file that happens to contain a secret-shaped
     token → operator returns content, ingestion redacts, no wall fires.
     (The pattern set is necessarily incomplete; redaction is the second
     line of defense after the path guard.)
"""
from __future__ import annotations

from pathlib import Path

from src.agent_session import AgentSessionState
from src.agent_state_machine import Action, State, violates_constitutional_wall
from src.state_machine_operators import ReadFileOperator

# See test_secret_redaction_on_tool_ingestion.py for why this is concat-built.
FAKE_SK_ANT = 'sk-' + 'ant-' + ('A' * 8) + ('b' * 8) + ('C' * 8) + ('d' * 8)


def _drive_read(session: AgentSessionState, path: Path, tool_call_id: str):
    """Mimic the runtime path: assistant calls Read, operator executes,
    session.append_tool stores the result. Returns the operator's observation
    so the caller can assert on it.
    """
    op = ReadFileOperator()
    state = State.fresh(session_id='smoke', budget_usd=1.0)
    action = Action(
        kind='tool_call',
        payload={'tool_name': 'read_file', 'path': str(path)},
    )
    obs = op.execute(action, state)
    # Assistant turn must precede the tool result (orphan-strip otherwise).
    session.append_assistant(
        content='',
        tool_calls=(
            {'id': tool_call_id, 'function': {'name': 'read_file', 'arguments': '{}'}},
        ),
    )
    # The runtime appends content on success or the error string on failure.
    # Either way, simulate the same ingestion path the runtime uses.
    if obs.kind == 'success':
        session.append_tool('read_file', tool_call_id, obs.payload['content'])
    else:
        session.append_tool('read_file', tool_call_id, str(obs.payload))
    return obs


def test_dotenv_read_refused_no_wedge_on_next_llm_call(tmp_path: Path):
    env = tmp_path / '.env'
    env.write_text(f'ANTHROPIC_API_KEY={FAKE_SK_ANT}\n')

    session = AgentSessionState.create(system_prompt_parts=['sys'], user_prompt='boot')
    obs = _drive_read(session, env, 'call_dotenv')

    # Path guard fired — content never read.
    assert obs.kind == 'error'
    assert obs.payload['refused_reason'] == 'secret_bearing_path'

    # The error string itself doesn't contain the secret (operator never
    # read the file content).
    assert FAKE_SK_ANT not in str(obs.payload)

    # Next llm_call payload is clean.
    payload = {'messages': session.to_openai_messages()}
    assert violates_constitutional_wall(Action(kind='llm_call', payload=payload)) is None


def test_safe_file_with_secret_inside_redacts_and_no_wedge(tmp_path: Path):
    """Defence-in-depth: a non-secret-bearing path whose content happens to
    contain a token shape. Path guard does NOT refuse; ingestion redaction
    catches it. Wall does not fire on the next llm_call.
    """
    leaky = tmp_path / 'README.md'
    leaky.write_text(f'old debug log: {FAKE_SK_ANT}\n')

    session = AgentSessionState.create(system_prompt_parts=['sys'], user_prompt='boot')
    obs = _drive_read(session, leaky, 'call_readme')

    # Path was not refused.
    assert obs.kind == 'success'
    # Operator's payload still has the raw content (operator doesn't redact;
    # ingestion does). This is intentional — separates concerns.
    assert FAKE_SK_ANT in obs.payload['content']

    # But session storage IS redacted (ingestion did its job).
    tool_msg = next(m for m in session.messages if m.role == 'tool')
    assert FAKE_SK_ANT not in tool_msg.content
    assert '[REDACTED:ant]' in tool_msg.content

    # And the wall does not fire on the next llm_call.
    payload = {'messages': session.to_openai_messages()}
    assert violates_constitutional_wall(Action(kind='llm_call', payload=payload)) is None
