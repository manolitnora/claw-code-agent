"""Terminal UI — Claude Code-style formatting for Latti.

Pure ANSI escape codes. Zero dependencies.
Pinned footer via scroll region — content scrolls above, footer stays at bottom.
"""

from __future__ import annotations

import os
import shutil
import sys

# ---------------------------------------------------------------------------
# ANSI codes
# ---------------------------------------------------------------------------

RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'
ITALIC = '\033[3m'
UNDERLINE = '\033[4m'

# Colors
BLUE = '\033[38;5;75m'
GREEN = '\033[38;5;78m'
YELLOW = '\033[38;5;220m'
CYAN = '\033[38;5;117m'
MAGENTA = '\033[38;5;176m'
RED = '\033[38;5;203m'
GRAY = '\033[38;5;245m'
WHITE = '\033[38;5;255m'
DARK_GRAY = '\033[38;5;240m'

# Background
BG_DARK = '\033[48;5;236m'
BG_CODE = '\033[48;5;235m'


def _w(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def _term_height() -> int:
    try:
        return shutil.get_terminal_size().lines
    except Exception:
        return 24


# ---------------------------------------------------------------------------
# State (set by the chat loop)
# ---------------------------------------------------------------------------

_state = {
    'model': os.environ.get('OPENAI_MODEL', 'unknown'),
    'cwd': '~',
    'context_pct': 0,
    'permissions': 'full',
    'total_tokens': 0,
    'turn_count': 0,
    'cost_usd': 0.0,
}


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
# Pinned footer (scroll region — content area above, footer pinned below)
# ---------------------------------------------------------------------------

_footer_active = False


def _setup_scroll_region() -> None:
    """Set terminal scroll region to leave 3 lines at bottom for footer."""
    global _footer_active
    rows = _term_height()
    _w(f'\033[1;{rows - 3}r')  # scroll region: line 1 to (rows-3)
    _footer_active = True


def _draw_footer() -> None:
    """Draw footer in the reserved area below the scroll region.

    Uses save/restore cursor so the content cursor doesn't move.
    """
    rows = _term_height()
    w = _term_width()
    model = _state['model']
    short_model = model.split('/')[-1] if '/' in model else model
    cwd = _state['cwd']
    pct = _state['context_pct']
    filled = max(0, pct // 10)
    empty = 10 - filled
    bar = '█' * filled + '░' * empty
    tokens = _state['total_tokens']
    turns = _state['turn_count']
    cost = _state['cost_usd']

    if tokens >= 1_000_000:
        tok_str = f'{tokens / 1_000_000:.1f}M'
    elif tokens >= 1_000:
        tok_str = f'{tokens / 1_000:.1f}K'
    else:
        tok_str = str(tokens)

    cost_str = f' │ ${cost:.4f}' if cost > 0.001 else ''

    line1 = '─' * w
    line2 = f'  {short_model} │ [{cwd}] {bar} {pct}%{cost_str}'
    line3 = f'  {tok_str} tokens │ turn {turns}'

    # Save cursor, draw in footer area, restore cursor
    _w('\0337')  # save cursor (DEC private — more reliable than \033[s)
    _w(f'\033[{rows - 2};1H{DARK_GRAY}{line1}\033[K{RESET}')
    _w(f'\033[{rows - 1};1H{DARK_GRAY}{line2}\033[K{RESET}')
    _w(f'\033[{rows};1H{DARK_GRAY}{line3}\033[K{RESET}')
    _w('\0338')  # restore cursor


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

def banner() -> None:
    _w('\033[2J\033[H')  # clear screen, cursor to top
    _w(f'\n{BLUE}{BOLD}  ◆ Latti Nora{RESET}{GRAY}  — lattice mind{RESET}\n')
    _w(f'{DARK_GRAY}  {"─" * 40}{RESET}\n\n')
    _setup_scroll_region()
    _draw_footer()


# ---------------------------------------------------------------------------
# Status footer update (public API — called after each turn)
# ---------------------------------------------------------------------------

def status_footer() -> None:
    """Redraw the pinned footer with current state."""
    if not _footer_active:
        _setup_scroll_region()
    _draw_footer()


# ---------------------------------------------------------------------------
# Prompt lane
# ---------------------------------------------------------------------------

def prompt() -> str:
    """Print the input lane and read input."""
    w = _term_width()

    # Top divider
    _w(f'{DARK_GRAY}{"─" * w}{RESET}\n')

    # Prompt arrow
    _w(f'{BLUE}{BOLD}❯  {RESET}')
    try:
        user_input = input()
    except (EOFError, KeyboardInterrupt):
        _w(f'\n{GRAY}  goodbye{RESET}\n')
        raise

    # Bottom divider
    _w(f'{DARK_GRAY}{"─" * w}{RESET}\n')

    return user_input


# ---------------------------------------------------------------------------
# Response streaming
# ---------------------------------------------------------------------------

class StreamRenderer:
    """Renders streaming markdown tokens to ANSI terminal output."""

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

            # Code block fence: ``` at line start
            if self._line_start and text[i:i+3] == '```':
                nl = text.find('\n', i + 3)
                if nl == -1:
                    self._pending = text[i:]
                    return
                if not self._in_code_block:
                    lang = text[i+3:nl].strip()
                    self._in_code_block = True
                    label = f' {lang} ' if lang else ''
                    _w(f'\n{DARK_GRAY}  ┌{"─" * 38}{RESET}\n')
                    if label:
                        _w(f'{DARK_GRAY}  │ {DIM}{CYAN}{label}{RESET}\n')
                else:
                    self._in_code_block = False
                    _w(f'{DARK_GRAY}  └{"─" * 38}{RESET}\n{WHITE}')
                i = nl + 1
                self._line_start = True
                continue

            # Inside code block
            if self._in_code_block:
                nl = text.find('\n', i)
                if nl == -1:
                    _w(f'{GREEN}{text[i:]}{RESET}')
                    return
                _w(f'{DARK_GRAY}  │ {GREEN}{text[i:nl]}{RESET}\n')
                i = nl + 1
                self._line_start = True
                continue

            # Bold marker **
            if text[i:i+2] == '**':
                if self._in_bold:
                    _w(RESET + WHITE)
                    self._in_bold = False
                else:
                    _w(BOLD + CYAN)
                    self._in_bold = True
                i += 2
                continue

            # Inline code `
            if ch == '`' and not self._in_code_block:
                if self._in_code_inline:
                    _w(RESET + WHITE)
                    self._in_code_inline = False
                else:
                    _w(DIM + YELLOW)
                    self._in_code_inline = True
                i += 1
                continue

            # Header # at line start
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

            # Newline
            if ch == '\n':
                _w('\n')
                i += 1
                self._line_start = True
                continue

            # Indent at line start
            if self._line_start:
                _w('  ')
                self._line_start = False

            # Regular character
            _w(ch)
            i += 1

    def end(self) -> None:
        if self._pending:
            _w(self._pending)
            self._pending = ''
        if self._in_bold:
            _w(RESET)
            self._in_bold = False
        if self._in_code_inline:
            _w(RESET)
            self._in_code_inline = False
        _w(f'{RESET}\n')


# ---------------------------------------------------------------------------
# Tool call display
# ---------------------------------------------------------------------------

def tool_start(name: str, detail: str = '') -> None:
    icon = _tool_icon(name)
    label = _tool_label(name)
    detail_str = f' {GRAY}{detail}{RESET}' if detail else ''
    _w(f'\n{DIM}{MAGENTA}  {icon} {label}{detail_str}{RESET}\n')


def tool_result(name: str, summary: str) -> None:
    _w(f'{DIM}{GRAY}  ⎿ {summary}{RESET}\n')


def tool_error(name: str, error: str) -> None:
    short = error[:120] if len(error) > 120 else error
    _w(f'{DIM}{RED}  ⎿ {short}{RESET}\n')


def _tool_icon(name: str) -> str:
    icons = {
        'read_file': '📄', 'write_file': '✏️', 'edit_file': '✏️',
        'bash': '⚡', 'glob_search': '🔍', 'grep_search': '🔍',
        'list_dir': '📁', 'lattice_solve': '◆', 'web_fetch': '🌐',
        'web_search': '🌐', 'delegate_agent': '🤖',
    }
    return icons.get(name, '⏺')


def _tool_label(name: str) -> str:
    labels = {
        'read_file': 'Read', 'write_file': 'Write', 'edit_file': 'Edit',
        'bash': 'Bash', 'glob_search': 'Glob', 'grep_search': 'Grep',
        'list_dir': 'List', 'lattice_solve': 'Lattice', 'web_fetch': 'Fetch',
        'web_search': 'Search', 'delegate_agent': 'Agent',
    }
    return labels.get(name, name)


# ---------------------------------------------------------------------------
# Info / status lines
# ---------------------------------------------------------------------------

def info(text: str) -> None:
    _w(f'{GRAY}  {text}{RESET}\n')


def divider() -> None:
    _w(f'{DARK_GRAY}  {"─" * 40}{RESET}\n')


# ---------------------------------------------------------------------------
# Done / thinking indicators
# ---------------------------------------------------------------------------

def done_marker() -> None:
    _w(f'\n{GREEN}{BOLD}  ◆ done{RESET}\n\n')


def thinking_start() -> None:
    _w(f'\n{DIM}{MAGENTA}  ◇ thinking…{RESET}')
    sys.stdout.flush()


def thinking_clear() -> None:
    _w(f'\033[A\033[2K')
    sys.stdout.flush()


def cleanup() -> None:
    """Restore normal terminal on exit."""
    global _footer_active
    if _footer_active:
        rows = _term_height()
        # Clear footer area
        _w(f'\033[{rows - 2};1H\033[J')
        # Reset scroll region to full terminal
        _w(f'\033[1;{rows}r')
        # Move cursor to bottom
        _w(f'\033[{rows};1H\n')
        _footer_active = False
