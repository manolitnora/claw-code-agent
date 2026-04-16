"""Terminal UI — Claude Code-style for Latti.

Layout matches Claude Code exactly:
- Content scrolls in upper region
- Footer pinned at bottom: divider │ prompt │ divider │ status

The ONLY cursor manipulation is in _draw_footer() and prompt().
Content functions (streaming, tools, info) just write to stdout.
The scroll region handles the rest.
"""

from __future__ import annotations

import os
import shutil
import sys

# ---------------------------------------------------------------------------
# ANSI
# ---------------------------------------------------------------------------

RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'
ITALIC = '\033[3m'
UNDERLINE = '\033[4m'

BLUE = '\033[38;5;75m'
GREEN = '\033[38;5;78m'
YELLOW = '\033[38;5;220m'
CYAN = '\033[38;5;117m'
MAGENTA = '\033[38;5;176m'
RED = '\033[38;5;203m'
GRAY = '\033[38;5;245m'
WHITE = '\033[38;5;255m'
DARK_GRAY = '\033[38;5;240m'

BG_DARK = '\033[48;5;236m'
BG_CODE = '\033[48;5;235m'

# Footer: divider + prompt + divider + status = 4 lines
_FOOTER_LINES = 4


def _w(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def _cols() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def _rows() -> int:
    try:
        return shutil.get_terminal_size().lines
    except Exception:
        return 24


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_state = {
    'model': os.environ.get('OPENAI_MODEL', 'unknown'),
    'cwd': '~',
    'context_pct': 0,
    'permissions': 'full access',
    'total_tokens': 0,
    'turn_count': 0,
    'cost_usd': 0.0,
}

_active = False


def set_state(
    *,
    model: str = '',
    cwd: str = '',
    context_pct: int = -1,
    permissions: str = '',
    total_tokens: int = -1,
    turn_count: int = -1,
    cost_usd: float = -1.0,
) -> None:
    if model:
        _state['model'] = model
    if cwd:
        home = os.path.expanduser('~')
        _state['cwd'] = cwd.replace(home, '~') if cwd.startswith(home) else cwd
    if context_pct >= 0:
        _state['context_pct'] = context_pct
    if permissions:
        _state['permissions'] = permissions
    if total_tokens >= 0:
        _state['total_tokens'] = total_tokens
    if turn_count >= 0:
        _state['turn_count'] = turn_count
    if cost_usd >= 0:
        _state['cost_usd'] = cost_usd


# ---------------------------------------------------------------------------
# Footer rendering — draws 4 lines at bottom of terminal
# ---------------------------------------------------------------------------

def _build_status() -> str:
    """Build the status line text."""
    model = _state['model']
    short = model.split('/')[-1] if '/' in model else model
    cwd = _state['cwd']
    pct = _state['context_pct']
    filled = max(0, pct // 10)
    bar = '█' * filled + '░' * (10 - filled)
    tok = _state['total_tokens']
    cost = _state['cost_usd']

    if tok >= 1_000_000:
        tok_s = f'{tok / 1_000_000:.1f}M'
    elif tok >= 1_000:
        tok_s = f'{tok / 1_000:.1f}K'
    else:
        tok_s = str(tok)

    cost_s = f' │ ${cost:.4f}' if cost > 0.001 else ''
    return f'  {short} │ [{cwd}] {bar} {pct}%{cost_s} │ {tok_s} tokens │ turn {_state["turn_count"]}'


def _draw_footer(prompt_text: str = '') -> None:
    """Draw the 4-line footer. Uses DEC save/restore.

    Layout:
      row r-3: ─────────── divider
      row r-2: ❯  {prompt_text or waiting}
      row r-1: ─────────── divider
      row r:   status line
    """
    r = _rows()
    c = _cols()
    div = '─' * c
    status = _build_status()

    _w('\0337')  # DEC save cursor
    _w(f'\033[{r-3};1H\033[2K{DARK_GRAY}{div}{RESET}')
    if prompt_text:
        _w(f'\033[{r-2};1H\033[2K{DARK_GRAY}  {prompt_text}{RESET}')
    else:
        _w(f'\033[{r-2};1H\033[2K{BLUE}{BOLD}❯  {RESET}')
    _w(f'\033[{r-1};1H\033[2K{DARK_GRAY}{div}{RESET}')
    _w(f'\033[{r};1H\033[2K{DARK_GRAY}{status}{RESET}')
    _w('\0338')  # DEC restore cursor


# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------

def banner() -> None:
    """Clear screen, set scroll region, draw footer, print banner text."""
    global _active
    r = _rows()
    _w('\033[2J\033[H')  # clear + cursor home
    _w(f'\033[1;{r - _FOOTER_LINES}r')  # scroll region: content area
    _active = True
    _draw_footer()
    # Banner text goes into the content area (cursor is at home)
    _w(f'\n{BLUE}{BOLD}  ◆ Latti Nora{RESET}{GRAY}  — lattice mind{RESET}\n')
    _w(f'{DARK_GRAY}  {"─" * 40}{RESET}\n\n')


def cleanup() -> None:
    """Restore terminal on exit."""
    global _active
    if _active:
        r = _rows()
        _w(f'\033[{r - 3};1H\033[J')  # clear footer area
        _w(f'\033[1;{r}r')             # reset scroll region
        _w(f'\033[{r};1H\n')           # cursor to bottom
        _active = False


def status_footer() -> None:
    """Redraw footer with current state. Called after each turn."""
    global _active
    if not _active:
        r = _rows()
        _w(f'\033[1;{r - _FOOTER_LINES}r')
        _active = True
    _draw_footer()


# ---------------------------------------------------------------------------
# Prompt — cursor moves to footer, then back to content area
# ---------------------------------------------------------------------------

def prompt() -> str:
    """Draw prompt in footer, get input, return cursor to content area."""
    r = _rows()
    content_bottom = r - _FOOTER_LINES

    # Draw the prompt line in the footer
    _w(f'\033[{r-2};1H\033[2K{BLUE}{BOLD}❯  {RESET}')

    # Cursor is now on the prompt line — input() reads here
    try:
        user_input = input()
    except (EOFError, KeyboardInterrupt):
        # Restore cursor to content area before raising
        _w(f'\033[{content_bottom};1H')
        _w(f'\n{GRAY}  goodbye{RESET}\n')
        raise

    # Show what was typed (dim, so it's clear the input was captured)
    _draw_footer(prompt_text=f'{DARK_GRAY}{user_input}{RESET}')

    # Return cursor to bottom of content area so response appears there
    _w(f'\033[{content_bottom};1H')

    return user_input


# ---------------------------------------------------------------------------
# Streaming — writes to content area, no cursor manipulation
# ---------------------------------------------------------------------------

class StreamRenderer:
    def __init__(self) -> None:
        self._in_bold = False
        self._in_code_inline = False
        self._in_code_block = False
        self._line_start = True
        self._pending = ''

    def start(self) -> None:
        _w(f'\n{WHITE}')
        self._line_start = True

    def token(self, text: str) -> None:
        text = self._pending + text
        self._pending = ''
        i = 0
        while i < len(text):
            ch = text[i]

            if self._line_start and text[i:i+3] == '```':
                nl = text.find('\n', i + 3)
                if nl == -1:
                    self._pending = text[i:]
                    return
                if not self._in_code_block:
                    lang = text[i+3:nl].strip()
                    self._in_code_block = True
                    _w(f'\n')
                    if lang:
                        _w(f'{DARK_GRAY}  {DIM}{CYAN}{lang}{RESET}\n')
                else:
                    self._in_code_block = False
                    _w(f'{RESET}\n{WHITE}')
                i = nl + 1
                self._line_start = True
                continue

            if self._in_code_block:
                nl = text.find('\n', i)
                if nl == -1:
                    _w(f'{GREEN}{text[i:]}{RESET}')
                    return
                _w(f'{GREEN}    {text[i:nl]}{RESET}\n')
                i = nl + 1
                self._line_start = True
                continue

            if text[i:i+2] == '**':
                if self._in_bold:
                    _w(RESET + WHITE)
                    self._in_bold = False
                else:
                    _w(BOLD + CYAN)
                    self._in_bold = True
                i += 2
                continue

            if ch == '`' and not self._in_code_block:
                if self._in_code_inline:
                    _w(RESET + WHITE)
                    self._in_code_inline = False
                else:
                    _w(DIM + YELLOW)
                    self._in_code_inline = True
                i += 1
                continue

            if self._line_start and ch == '#':
                nl = text.find('\n', i)
                if nl == -1:
                    self._pending = text[i:]
                    return
                line = text[i:nl].lstrip('#').strip()
                _w(f'{BOLD}{BLUE}{line}{RESET}\n{WHITE}')
                i = nl + 1
                self._line_start = True
                continue

            if ch == '\n':
                _w('\n')
                i += 1
                self._line_start = True
                continue

            if self._line_start:
                _w('  ')
                self._line_start = False

            _w(ch)
            i += 1

    def end(self) -> None:
        if self._pending:
            _w(self._pending)
            self._pending = ''
        if self._in_bold:
            _w(RESET)
        if self._in_code_inline:
            _w(RESET)
        _w(f'{RESET}\n')


# ---------------------------------------------------------------------------
# Tool calls — write to content area, no cursor manipulation
# ---------------------------------------------------------------------------

def tool_start(name: str, detail: str = '') -> None:
    icon = _tool_icon(name)
    label = _tool_label(name)
    d = f' {GRAY}{detail}{RESET}' if detail else ''
    _w(f'\n{DIM}{MAGENTA}  {icon} {label}{d}{RESET}\n')

def tool_result(name: str, summary: str) -> None:
    _w(f'{DIM}{GRAY}  ⎿ {summary}{RESET}\n')

def tool_error(name: str, error: str) -> None:
    _w(f'{DIM}{RED}  ⎿ {error[:120]}{RESET}\n')

def _tool_icon(name: str) -> str:
    return {
        'read_file': '📄', 'write_file': '✏️', 'edit_file': '✏️',
        'bash': '⚡', 'glob_search': '🔍', 'grep_search': '🔍',
        'list_dir': '📁', 'lattice_solve': '◆', 'web_fetch': '🌐',
        'web_search': '🌐', 'delegate_agent': '🤖',
    }.get(name, '⏺')

def _tool_label(name: str) -> str:
    return {
        'read_file': 'Read', 'write_file': 'Write', 'edit_file': 'Edit',
        'bash': 'Bash', 'glob_search': 'Glob', 'grep_search': 'Grep',
        'list_dir': 'List', 'lattice_solve': 'Lattice', 'web_fetch': 'Fetch',
        'web_search': 'Search', 'delegate_agent': 'Agent',
    }.get(name, name)


# ---------------------------------------------------------------------------
# Info / markers — write to content area, no cursor manipulation
# ---------------------------------------------------------------------------

def info(text: str) -> None:
    _w(f'{GRAY}  {text}{RESET}\n')

def divider() -> None:
    _w(f'{DARK_GRAY}  {"─" * 40}{RESET}\n')

def done_marker() -> None:
    _w(f'\n{GREEN}{BOLD}  ◆ done{RESET}\n\n')

def thinking_start() -> None:
    _w(f'\n{DIM}{MAGENTA}  ◇ thinking…{RESET}')
    sys.stdout.flush()

def thinking_clear() -> None:
    _w('\033[A\033[2K')
    sys.stdout.flush()
