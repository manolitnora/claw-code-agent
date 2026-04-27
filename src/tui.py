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
import select
import shutil
import sys
import termios
import tty

# ---------------------------------------------------------------------------
# ANSI
# ---------------------------------------------------------------------------

RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'
ITALIC = '\033[3m'
UNDERLINE = '\033[4m'

BLUE = '\033[38;5;75m'
GREEN = '\033[38;5;114m'
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
_last_rows: int = 0  # track terminal height; re-establish scroll region on change


def _ensure_scroll_region() -> None:
    """(Re-)set the scroll region to the content area.

    Called at every footer draw and at prompt entry so that terminal resize
    or any escape sequence that resets the scroll region never corrupts the
    layout.  Safe to call when the region is already correct — the terminal
    ignores a no-op set.
    """
    global _last_rows, _active
    r = _rows()
    if r != _last_rows or not _active:
        _w(f'\033[1;{r - _FOOTER_LINES}r')  # scroll region: rows 1..(r-4)
        _last_rows = r
        _active = True


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
    line = f'  {short} │ [{cwd}] {bar} {pct}%{cost_s} │ {tok_s} tokens │ turn {_state["turn_count"]}'
    # Truncate to terminal width so the status line never wraps and corrupts
    # the footer layout (wrapping pushes the prompt row into the scroll region,
    # causing the "bouncing" / input corruption bug).
    max_w = _cols()
    if len(line) > max_w:
        line = line[:max_w - 1] + '…'
    return line


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

    _ensure_scroll_region()
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
    global _active, _last_rows
    r = _rows()
    _w('\033[2J\033[H')  # clear + cursor home
    _w(f'\033[1;{r - _FOOTER_LINES}r')  # scroll region: content area
    _active = True
    _last_rows = r
    _draw_footer()
    # Banner text goes into the content area (cursor is at home)
    _w(f'\n{BLUE}{BOLD}  ◆ Latti Nora{RESET}{GRAY}  — lattice mind{RESET}\n')
    _w(f'{DARK_GRAY}  {"─" * 40}{RESET}\n\n')


def cleanup() -> None:
    """Restore terminal on exit."""
    global _active, _last_rows
    if _active:
        r = _rows()
        _w(f'\033[{r - 3};1H\033[J')  # clear footer area
        _w(f'\033[1;{r}r')             # reset scroll region to full terminal
        _w(f'\033[{r};1H\n')           # cursor to bottom
        _active = False
        _last_rows = 0


def status_footer() -> None:
    """Redraw footer with current state. Called after each turn."""
    _ensure_scroll_region()  # re-establishes region if rows changed
    _draw_footer()


# ---------------------------------------------------------------------------
# Prompt — cursor moves to footer, then back to content area
# ---------------------------------------------------------------------------

# Paste detection: if a second line arrives within this many seconds of the
# first, we're in paste mode and keep collecting until a deliberate Enter on
# a blank line (or Ctrl+D).
_PASTE_TIMEOUT = 0.08  # 80 ms — fast enough for paste, slow for human typing


def _read_multiline() -> str:
    """Read one user message, handling multi-line paste correctly.

    UX contract:
    - Single line + Enter  → submit immediately (normal case, unchanged)
    - Paste (lines arrive <80ms apart) → collect all lines; show "[N lines]"
      indicator; submit when user presses Enter on a blank line or Ctrl+D
    - Ctrl+D on empty buffer → raise EOFError
    - Ctrl+C → raise KeyboardInterrupt

    Uses raw terminal mode so we can peek at stdin with select() without
    blocking. Restores cooked mode before returning.
    """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    lines: list[str] = []
    current: list[str] = []  # chars on the current line

    def _flush_line() -> str:
        line = ''.join(current)
        current.clear()
        return line

    def _update_prompt_indicator(n_lines: int) -> None:
        """Redraw the prompt row to show multiline indicator."""
        r = _rows()
        if n_lines > 0:
            indicator = f'{BLUE}{BOLD}❯  {RESET}{CYAN}[{n_lines} line{"s" if n_lines != 1 else ""} — blank line or Ctrl+D to send]{RESET}'
        else:
            indicator = f'{BLUE}{BOLD}❯  {RESET}'
        _w(f'\033[{r-2};1H\033[2K{indicator}')

    try:
        tty.setraw(fd)

        while True:
            # Wait for input; use a short timeout when we already have lines
            # (so we can detect end-of-paste)
            timeout = _PASTE_TIMEOUT if lines else None
            ready, _, _ = select.select([sys.stdin], [], [], timeout)

            if not ready:
                # Timeout expired with no new data — paste is done.
                # If we have collected lines, wait for explicit submit.
                # (We stay in the loop; next keypress will decide.)
                continue

            ch = sys.stdin.read(1)

            # Ctrl+C
            if ch == '\x03':
                raise KeyboardInterrupt

            # Ctrl+D
            if ch == '\x04':
                if not current and not lines:
                    raise EOFError
                # Treat as submit
                if current:
                    lines.append(_flush_line())
                break

            # Enter / Return
            if ch in ('\r', '\n'):
                line = _flush_line()

                if lines:
                    # We're in multiline mode.
                    if line == '':
                        # Blank line = submit
                        break
                    else:
                        lines.append(line)
                        _update_prompt_indicator(len(lines))
                else:
                    # First line — check if more data arrives quickly (paste)
                    ready2, _, _ = select.select([sys.stdin], [], [], _PASTE_TIMEOUT)
                    if ready2:
                        # More data incoming → paste mode
                        lines.append(line)
                        _update_prompt_indicator(len(lines))
                    else:
                        # Nothing more → single-line submit
                        lines.append(line)
                        break
                continue

            # Backspace (raw mode sends \x7f or \x08)
            if ch in ('\x7f', '\x08'):
                if current:
                    current.pop()
                    _w('\b \b')  # erase last char on screen
                continue

            # Printable character — echo it
            current.append(ch)
            _w(ch)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    return '\n'.join(lines)


def prompt() -> str:
    """Draw prompt in footer, get input, return cursor to content area."""
    _ensure_scroll_region()  # guard against resize between turns
    r = _rows()
    content_bottom = r - _FOOTER_LINES

    # Draw the prompt line in the footer
    _w(f'\033[{r-2};1H\033[2K{BLUE}{BOLD}❯  {RESET}')

    try:
        user_input = _read_multiline()
    except (EOFError, KeyboardInterrupt):
        # Restore cursor to content area before raising
        _w(f'\033[{content_bottom};1H')
        _w(f'\n{GRAY}  goodbye{RESET}\n')
        raise

    # Show what was typed (dim summary — truncate long pastes)
    summary = user_input.replace('\n', ' ↵ ')
    if len(summary) > 80:
        summary = summary[:77] + '…'
    _draw_footer(prompt_text=f'{DARK_GRAY}{summary}{RESET}')

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
                    _w(YELLOW)
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
    d = f' {CYAN}{detail}{RESET}' if detail else ''
    _w(f'\n{MAGENTA}  {icon} {label}{d}{RESET}\n')

def tool_result(name: str, summary: str) -> None:
    try:
        from .tui_heal import sanitize as _sanitize
        summary = _sanitize(summary)
    except Exception:
        pass
    _w(f'{GRAY}  ⎿ {summary}{RESET}\n')

def tool_error(name: str, error: str) -> None:
    try:
        from .tui_heal import sanitize as _sanitize
        error = _sanitize(error)
    except Exception:
        pass
    _w(f'{RED}  ⎿ {error[:120]}{RESET}\n')

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
    _w(f'\n{MAGENTA}  ◇ thinking…{RESET}')
    sys.stdout.flush()

def thinking_clear() -> None:
    _w('\033[A\033[2K')
    sys.stdout.flush()

def thinking_block(thinking_text: str, token_count: int = 0) -> None:
    """Display extended thinking from o1/o3 models."""
    if not thinking_text:
        return
    _w(f'\n{MAGENTA}[THINKING]{RESET}')
    if token_count > 0:
        _w(f' {CYAN}({token_count} tokens){RESET}')
    _w('\n')
    # Truncate very long thinking to first 500 chars for display
    display_text = thinking_text[:500]
    if len(thinking_text) > 500:
        display_text += f'\n{CYAN}... ({len(thinking_text) - 500} more chars){RESET}'
    _w(display_text)
    _w('\n')
    sys.stdout.flush()

def scar_match(scar_id: str, lesson: str, model: str) -> None:
    """Display when a scar matches and influences routing."""
    _w(f'\n{GREEN}[SCAR MATCH]{RESET} {scar_id}\n')
    _w(f'{CYAN}Lesson:{RESET} {lesson}\n')
    _w(f'{CYAN}Using model:{RESET} {model}\n')
    sys.stdout.flush()
