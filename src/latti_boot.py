"""Latti Boot Hook — runs BEFORE the first LLM call.

Gathers system state and injects it into the context so the LLM
receives boot results, not boot instructions. The model doesn't
need to think about booting — the code already did it.

Called from main.py before _run_agent_chat_loop when LATTI_BOOT=1.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


LATTI_HOME = Path(os.environ.get('LATTI_HOME', os.path.expanduser('~/.latti')))
SHARED_MEMORY = Path(os.path.expanduser(
    '~/.claude/projects/-Users-manolitonora-V5/memory'
))


def _read_safe(path: Path, limit: int = 2000) -> str:
    """Read a file safely, return empty string on failure."""
    try:
        text = path.read_text(encoding='utf-8')
        return text[:limit]
    except (OSError, UnicodeDecodeError):
        return ''


def _run_safe(cmd: str, timeout: int = 5) -> str:
    """Run a shell command safely, return output or empty string."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()[:500]
    except (subprocess.TimeoutExpired, OSError):
        return ''


def _run_boot_services() -> str:
    """Run Latti's boot.sh to auto-start services. Returns status line."""
    boot_sh = LATTI_HOME / 'boot.sh'
    if boot_sh.exists():
        output = _run_safe(f'bash {boot_sh}', timeout=15)
        # Extract the SYSTEM: line
        for line in output.split('\n'):
            if line.startswith('SYSTEM:'):
                return line
    return ''


def gather_boot_context() -> str:
    """Gather system state and return it as a formatted string for injection."""
    sections: list[str] = []

    # 0. Run boot.sh to auto-start services (code, not instructions)
    svc_status = _run_boot_services()
    if svc_status:
        sections.append(f'# {svc_status}')

    # 1. Latti's own memory index
    memory_md = _read_safe(LATTI_HOME / 'memory' / 'MEMORY.md', limit=3000)
    if memory_md:
        sections.append(f'# YOUR MEMORY (loaded at boot — do NOT read MEMORY.md again)\n\n{memory_md}')

    # 2. Current project state
    current_state = _read_safe(SHARED_MEMORY / 'project_current_state.md', limit=1500)
    if current_state:
        sections.append(f'# CURRENT STATE (shared from Claude Code)\n\n{current_state}')

    # 3. Live state — last action, next action
    live_state = _read_safe(Path('~/.claude/live-state.md').expanduser(), limit=800)
    if live_state:
        sections.append(f'# LIVE STATE\n\n{live_state}')

    # 4. NBA engine status (detailed — if boot.sh started it)
    nba = _run_safe('curl -s http://localhost:3737/api/dashboard 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); r=d[\'record\']; print(f\'${d[\"balance\"]:.2f} | {r[\"wins\"]}-{r[\"losses\"]}-{r[\"pushes\"]} | ROI {d[\"roi\"]}%\')" 2>/dev/null')
    if nba:
        sections.append(f'# NBA ENGINE: {nba}')

    # 6. Architecture and autonomy level
    arch = _read_safe(LATTI_HOME / 'ARCHITECTURE.md', limit=500)
    if arch:
        # Just the quick reference table, not the full doc
        table_end = arch.find('## How You Work')
        if table_end > 0:
            sections.append(f'# YOUR ARCHITECTURE (summary — read ~/.latti/ARCHITECTURE.md for full)\n\n{arch[:table_end]}')

    autonomy = _read_safe(LATTI_HOME / 'AUTONOMY.md', limit=1000)
    if autonomy:
        sections.append(f'# YOUR AUTONOMY LEVELS\n\n{autonomy}')

    # 7. Date and time
    date_str = _run_safe('date "+%Y-%m-%d %H:%M %Z"')
    if date_str:
        sections.append(f'# NOW: {date_str}')

    if not sections:
        return ''

    header = '# ═══ BOOT CONTEXT (auto-gathered — not from the model) ═══\n\n'
    return header + '\n\n'.join(sections)
