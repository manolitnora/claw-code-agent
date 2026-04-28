"""Terminal UI — pi-style dark-green aesthetic for Latti.

Layout:
- Content scrolls in upper region (scroll region)
- Footer pinned at bottom: divider │ prompt │ divider │ status (2 lines)

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
# ANSI — dark-green palette matching pi TUI
# ---------------------------------------------------------------------------

RESET      = '\033[0m'
BOLD       = '\033[1m'
DIM        = '\033[2m'
ITALIC     = '\033[3m'

# Greens
G_BRIGHT   = '\033[38;5;82m'   # bright green  — commands, highlights
G_MID      = '\033[38;5;71m'   # mid green     — tool labels
G_DIM      = '\033[38;5;28m'   # dark green     — subtle accents

# Text
WHITE      = '\033[38;5;255m'  # response body
GRAY       = '\033[38;5;245m'  # secondary info
DARK_GRAY  = '\033[38;5;240m'  # dividers, dims
OFF_WHITE  = '\033[38;5;252m'  # user input echo

# Accents
YELLOW     = '\033[38;5;220m'  # inline code
CYAN       = '\033[38;5;117m'  # bold spans
RED        = '\033[38;5;203m'  # errors
ORANGE     = '\033[38;5;214m'  # warnings / thinking

# Backgrounds
BG_USER    = '\033[48;5;22m'   # dark green bg for user message band
BG_TOOL    = '\033[48;5;235m'  # very dark bg for tool header

# Keep legacy aliases so external callers don't break
BLUE       = '\033[38;5;75m'
GREEN      = G_BRIGHT
MAGENTA    = '\033[38;5;176m'

# Footer height: top-divider + prompt-row + bottom-divider + status1 + status2 = 5 lines
_FOOTER_LINES = 5


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
    'model':        os.environ.get('OPENAI_MODEL', 'unknown'),
    'cwd':          '~',
    'context_pct':  0,
    'permissions':  'full access',
    'total_tokens': 0,
    'turn_count':   0,
    'cost_usd':     0.0,
    'branch':       '',
    'session_id':   '',
}

_active    = False
_last_rows: int = 0


def _ensure_scroll_region() -> None:
    """(Re-)set the scroll region to the content area.

    Called at every footer draw and at prompt entry so that terminal resize
    or any escape sequence that resets the scroll region never corrupts the
    layout.  Safe to call when the region is already correct.
    """
    global _last_rows, _active
    r = _rows()
    if r != _last_rows or not _active:
        _w(f'\033[1;{r - _FOOTER_LINES}r')
        _last_rows = r
        _active = True


def set_state(
    *,
    model:        str   = '',
    cwd:          str   = '',
    context_pct:  int   = -1,
    permissions:  str   = '',
    total_tokens: int   = -1,
    turn_count:   int   = -1,
    cost_usd:     float = -1.0,
    branch:       str   = '',
    session_id:   str   = '',
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
    if branch:
        _state['branch'] = branch
    if session_id:
        _state['session_id'] = session_id


# ---------------------------------------------------------------------------
# Footer rendering — 5 lines pinned at bottom
#
#  row r-4: ── divider ────────────────────────────────────────────────────
#  row r-3: ❯  {prompt text or cursor}
#  row r-2: ── divider ────────────────────────────────────────────────────
#  row r-1: status line 1  — project │ branch │ session │ turns
#  row r:   status line 2  — model │ context bar │ cost │ tokens
# ---------------------------------------------------------------------------

def _fmt_tokens(tok: int) -> str:
    if tok >= 1_000_000:
        return f'{tok / 1_000_000:.1f}M'
    if tok >= 1_000:
        return f'{tok / 1_000:.1f}k'
    return str(tok)


def _build_status1() -> str:
    """Top status line: project path │ branch │ session │ turns."""
    c = _cols()
    cwd  = _state['cwd']
    branch = _state['branch']
    sess = _state['session_id'][:8] if _state['session_id'] else ''
    turn = _state['turn_count']

    parts = [f'  {G_BRIGHT}{cwd}{RESET}']
    if branch:
        parts.append(f'{DARK_GRAY}({G_MID}{branch}{DARK_GRAY}){RESET}')
    if sess:
        parts.append(f'{DARK_GRAY}sess:{GRAY}{sess}{RESET}')
    parts.append(f'{DARK_GRAY}turn {GRAY}{turn}{RESET}')
    line = f'  {DARK_GRAY}│{RESET} '.join(parts)
    # strip ANSI for length check
    import re as _re
    plain = _re.sub(r'\033\[[^m]*m', '', line)
    if len(plain) > c:
        # fallback: just cwd + turn
        line = f'  {G_BRIGHT}{cwd}{RESET}  {DARK_GRAY}turn {GRAY}{turn}{RESET}'
    return line


def _build_status2() -> str:
    """Bottom status line: model │ context bar │ cost │ tokens."""
    c      = _cols()
    model  = _state['model']
    short  = model.split('/')[-1] if '/' in model else model
    pct    = _state['context_pct']
    filled = max(0, pct // 10)
    bar    = f'{G_BRIGHT}{"█" * filled}{DARK_GRAY}{"░" * (10 - filled)}{RESET}'
    tok    = _fmt_tokens(_state['total_tokens'])
    cost   = _state['cost_usd']
    cost_s = f'${cost:.4f}' if cost > 0.001 else '$0.00'

    line = f'  {G_MID}{short}{RESET}  {bar}  {GRAY}{pct}%{RESET}  {DARK_GRAY}│{RESET}  {GRAY}{cost_s}{RESET}  {DARK_GRAY}│{RESET}  {GRAY}{tok} tokens{RESET}'

    import re as _re
    plain = _re.sub(r'\033\[[^m]*m', '', line)
    if len(plain) > c:
        line = line[:c - 1]
    return line


def _draw_footer(prompt_text: str = '') -> None:
    """Draw the 5-line footer at absolute row positions.

    No DEC save/restore — that was causing cursor corruption (the save would
    capture a footer-row position after any drift, and restore would put the
    cursor back there, splitting subsequent content into two columns).

    Contract: after this call the cursor sits at content_bottom.  Callers
    that need the cursor somewhere else (e.g. banner → row 1) must move it
    explicitly AFTER calling _draw_footer.
    """
    _ensure_scroll_region()
    r = _rows()
    c = _cols()
    div   = f'{DARK_GRAY}{"─" * c}{RESET}'
    stat1 = _build_status1()
    stat2 = _build_status2()

    content_bottom = r - _FOOTER_LINES
    _w(f'\033[{r-4};1H\033[2K{div}')
    if prompt_text:
        _w(f'\033[{r-3};1H\033[2K{DARK_GRAY}  {prompt_text}{RESET}')
    else:
        _w(f'\033[{r-3};1H\033[2K{G_BRIGHT}{BOLD}❯  {WHITE}')
    _w(f'\033[{r-2};1H\033[2K{div}')
    _w(f'\033[{r-1};1H\033[2K{stat1}')
    _w(f'\033[{r};1H\033[2K{stat2}')
    # Land cursor at content_bottom — safe position for content writes
    _w(f'\033[{content_bottom};1H')


# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------

def banner() -> None:
    """Clear screen, set scroll region, draw footer, print banner."""
    global _active, _last_rows
    r = _rows()
    _w('\033[2J\033[H')
    _w(f'\033[1;{r - _FOOTER_LINES}r')
    _active    = True
    _last_rows = r
    _draw_footer()
    # _draw_footer lands cursor at content_bottom — move back to top so
    # banner text and boot info flow from row 1 downward.
    _w('\033[1;1H')
    _w(f'\n{G_BRIGHT}{BOLD}  ◆ Latti{RESET}{GRAY}  — lattice mind{RESET}\n')
    _w(f'{DARK_GRAY}  {"─" * 40}{RESET}\n\n')


def cleanup() -> None:
    """Restore terminal on exit."""
    global _active, _last_rows
    if _active:
        r = _rows()
        _w(f'\033[{r - 4};1H\033[J')
        _w(f'\033[1;{r}r')
        _w(f'\033[{r};1H\n')
        _active    = False
        _last_rows = 0


def status_footer() -> None:
    """Redraw footer with current state. Called after each turn.

    _draw_footer() lands cursor at content_bottom — correct for next
    content write (streaming response starts there and scrolls upward).
    """
    _ensure_scroll_region()
    _draw_footer()


# ---------------------------------------------------------------------------
# Prompt — cursor moves to footer, then back to content area
# ---------------------------------------------------------------------------

_PASTE_TIMEOUT = 0.08


def _read_multiline() -> str:
    """Read one user message, handling multi-line paste correctly."""
    fd           = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    lines: list[str] = []
    current: list[str] = []

    def _flush_line() -> str:
        line = ''.join(current)
        current.clear()
        return line

    def _update_prompt_indicator(n_lines: int) -> None:
        r = _rows()
        if n_lines > 0:
            indicator = (
                f'{G_BRIGHT}{BOLD}❯  {RESET}{CYAN}'
                f'[{n_lines} line{"s" if n_lines != 1 else ""}'
                f' — blank line or Ctrl+D to send]{WHITE}'
            )
        else:
            indicator = f'{G_BRIGHT}{BOLD}❯  {WHITE}'
        _w(f'\033[{r-3};1H\033[2K{indicator}')

    try:
        tty.setraw(fd)

        while True:
            timeout = _PASTE_TIMEOUT if lines else None
            ready, _, _ = select.select([sys.stdin], [], [], timeout)

            if not ready:
                continue

            ch = sys.stdin.read(1)

            if ch == '\x03':
                raise KeyboardInterrupt
            if ch == '\x04':
                if not current and not lines:
                    raise EOFError
                if current:
                    lines.append(_flush_line())
                break

            if ch in ('\r', '\n'):
                line = _flush_line()
                if lines:
                    if line == '':
                        break
                    else:
                        lines.append(line)
                        _update_prompt_indicator(len(lines))
                else:
                    ready2, _, _ = select.select([sys.stdin], [], [], _PASTE_TIMEOUT)
                    if ready2:
                        lines.append(line)
                        _update_prompt_indicator(len(lines))
                    else:
                        lines.append(line)
                        break
                continue

            if ch in ('\x7f', '\x08'):
                if current:
                    current.pop()
                    _w('\b \b')
                continue

            current.append(ch)
            _w(ch)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    return '\n'.join(lines)


def prompt() -> str:
    """Draw prompt in footer, get input, return cursor to content area."""
    _ensure_scroll_region()
    r            = _rows()
    content_bottom = r - _FOOTER_LINES

    _w(f'\033[{r-3};1H\033[2K{G_BRIGHT}{BOLD}❯  {WHITE}')

    try:
        user_input = _read_multiline()
    except (EOFError, KeyboardInterrupt):
        _w(f'\033[{content_bottom};1H')
        _w(f'\n{GRAY}  goodbye{RESET}\n')
        raise

    summary = user_input.replace('\n', ' ↵ ')
    if len(summary) > 80:
        summary = summary[:77] + '…'
    _draw_footer(prompt_text=f'{DARK_GRAY}{summary}{RESET}')
    _w(f'\033[{content_bottom};1H')
    return user_input


# ---------------------------------------------------------------------------
# User message echo — pi-style highlighted band
# ---------------------------------------------------------------------------

def user_message(text: str) -> None:
    """Display the user's message as a highlighted dark-green band."""
    lines = text.split('\n') if '\n' in text else [text]
    _w('\n')
    for line in lines:
        _w(f'{BG_USER}{OFF_WHITE}  {line}\033[K{RESET}\n')
    _w(RESET)


# ---------------------------------------------------------------------------
# Streaming — writes to content area, no cursor manipulation
# ---------------------------------------------------------------------------

class StreamRenderer:
    def __init__(self) -> None:
        self._in_bold        = False
        self._in_code_inline = False
        self._in_code_block  = False
        self._line_start     = True
        self._pending        = ''

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
                    _w('\n')
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
                    _w(f'{G_BRIGHT}{text[i:]}{RESET}')
                    return
                _w(f'{G_BRIGHT}    {text[i:nl]}{RESET}\n')
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
                _w(f'{BOLD}{G_BRIGHT}{line}{RESET}\n{WHITE}')
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
# Tool calls — pi-style: $ command header + truncated output + separator
# ---------------------------------------------------------------------------

# Track lines seen per tool call for the expand hint
_tool_line_counts: dict[str, int] = {}


def tool_start(name: str, detail: str = '') -> None:
    """pi-style tool header: dark band with icon + label + command."""
    icon  = _tool_icon(name)
    label = _tool_label(name)
    cmd   = detail if detail else label
    # Truncate so line never wraps (wrapping corrupts scroll region)
    max_cmd = max(10, _cols() - len(label) - 10)
    if len(cmd) > max_cmd:
        cmd = cmd[:max_cmd - 1] + '…'
    _w(f'\n{BG_TOOL}{G_MID}{BOLD}{icon} {label}{RESET}{BG_TOOL}  {DARK_GRAY}{cmd}\033[K{RESET}\n')


def tool_result(name: str, summary: str) -> None:
    """Output line + pi-style separator with inline metadata."""
    try:
        from .tui_heal import sanitize as _sanitize
        summary = _sanitize(summary)
    except Exception:
        pass

    # Count lines for expand hint
    n_lines = summary.count('\n') + 1
    _tool_line_counts[name] = n_lines

    # Show first line of output
    first = summary.split('\n')[0]
    if len(first) > 120:
        first = first[:117] + '…'

    _w(f'{DARK_GRAY}  ⎿ {GRAY}{first}{RESET}\n')

    # Truncation hint if multi-line (pi-style)
    if n_lines > 1:
        _w(f'{DARK_GRAY}  … ({n_lines - 1} more line{"s" if n_lines > 2 else ""}, not shown){RESET}\n')

    # Thin separator — use \033[K so it never wraps on narrow terminals
    _w(f'{DARK_GRAY}  {"─" * (_cols() - 2)}{RESET}\n')


def tool_error(name: str, error: str) -> None:
    try:
        from .tui_heal import sanitize as _sanitize
        error = _sanitize(error)
    except Exception:
        pass
    _w(f'{RED}  ⎿ {error[:120]}{RESET}\n')
    _w(f'{DARK_GRAY}  {"─" * (_cols() - 2)}{RESET}\n')


def _tool_icon(name: str) -> str:
    return {
        'read_file':      '📄',
        'write_file':     '✏️',
        'edit_file':      '✏️',
        'bash':           '⚡',
        'glob_search':    '🔍',
        'grep_search':    '🔍',
        'list_dir':       '📁',
        'lattice_solve':  '◆',
        'lattice_boolean_solve': '◆',
        'web_fetch':      '🌐',
        'web_search':     '🌐',
        'delegate_agent': '🤖',
        'self_score':     '📊',
    }.get(name, '⏺')


def _tool_label(name: str) -> str:
    return {
        'read_file':      'Read',
        'write_file':     'Write',
        'edit_file':      'Edit',
        'bash':           'Bash',
        'glob_search':    'Glob',
        'grep_search':    'Grep',
        'list_dir':       'List',
        'lattice_solve':  'Lattice',
        'lattice_boolean_solve': 'Lattice Bool',
        'web_fetch':      'Fetch',
        'web_search':     'Search',
        'delegate_agent': 'Agent',
        'self_score':     'Score',
    }.get(name, name)


# ---------------------------------------------------------------------------
# Info / markers
# ---------------------------------------------------------------------------

def info(text: str) -> None:
    _w(f'{DARK_GRAY}  {GRAY}{text}{RESET}\n')

def divider() -> None:
    c = _cols()
    _w(f'{DARK_GRAY}{"─" * c}{RESET}\n')

def done_marker() -> None:
    _w(f'\n{G_BRIGHT}{BOLD}  ◆ done{RESET}\n\n')

def thinking_start() -> None:
    _w(f'\n{ORANGE}  ⏳ Working…{RESET}')
    sys.stdout.flush()

def thinking_clear() -> None:
    _w('\033[A\033[2K')
    sys.stdout.flush()

def thinking_block(thinking_text: str, token_count: int = 0) -> None:
    if not thinking_text:
        return
    _w(f'\n{ORANGE}[thinking]{RESET}')
    if token_count > 0:
        _w(f' {CYAN}({token_count} tokens){RESET}')
    _w('\n')
    display_text = thinking_text[:500]
    if len(thinking_text) > 500:
        display_text += f'\n{CYAN}… ({len(thinking_text) - 500} more chars){RESET}'
    _w(display_text)
    _w('\n')
    sys.stdout.flush()

def scar_match(scar_id: str, lesson: str, model: str) -> None:
    _w(f'\n{G_MID}[scar]{RESET} {GRAY}{scar_id}{RESET}\n')
    _w(f'{DARK_GRAY}  lesson:{RESET} {GRAY}{lesson}{RESET}\n')
    _w(f'{DARK_GRAY}  model: {RESET} {G_BRIGHT}{model}{RESET}\n')
    sys.stdout.flush()
