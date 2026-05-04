"""TUI tool_result / tool_error redact secret-shaped tokens.

The live test against Latti revealed that the TUI's preview line displays
the raw tool output independently of message history — so even though the
model never sees the secret, anyone watching the terminal does. This pins
the closure of that display-layer leak.
"""
from __future__ import annotations

import io
import sys

import src.tui as tui

# See test_secret_redaction_on_tool_ingestion.py for why this is concat-built.
FAKE_SK_ANT = 'sk-' + 'ant-' + ('A' * 8) + ('b' * 8) + ('C' * 8) + ('d' * 8)


def _capture_stdout(fn):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


def test_tool_result_redacts_secret():
    out = _capture_stdout(
        lambda: tui.tool_result('read_file', f'API_KEY={FAKE_SK_ANT}\n')
    )
    assert FAKE_SK_ANT not in out
    assert '[REDACTED:ant]' in out


def test_tool_error_redacts_secret_in_error_message():
    """Error paths can also surface secrets — e.g., a stack trace from a
    tool that loaded then failed on env content. Pin redaction there too.
    """
    out = _capture_stdout(
        lambda: tui.tool_error('read_file', f'failed parsing: {FAKE_SK_ANT}')
    )
    assert FAKE_SK_ANT not in out
    assert '[REDACTED:ant]' in out


def test_tool_result_passes_through_clean_output():
    out = _capture_stdout(
        lambda: tui.tool_result('read_file', 'hello world')
    )
    assert 'hello world' in out
