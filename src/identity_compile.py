# src/identity_compile.py
"""Compile Latti's typed substrate into IDENTITY.md (now-file) + HISTORY.md.

See docs/superpowers/specs/2026-05-01-latti-self-writing-identity-design.md.

Substrate read is *typed-only*: file must start with '---\n' AND parse via
LattiMemoryStore.load(). Legacy markdown files in ~/.latti/memory/ are
invisible to identity by design (~98% are operational debris).
"""
from __future__ import annotations

import datetime
import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Iterator

from src.agent_state_machine import MemoryRecord
from src.state_machine_memory import LattiMemoryStore
from src.identity_templates import (
    WHERE_SECTION, LEARNING_SECTION, IDENTITY_MD,
    PLACEHOLDER_NO_GOALS, PLACEHOLDER_NO_RECORDS,
    PLACEHOLDER_NO_SCARS, PLACEHOLDER_NO_LESSONS,
)


def load_typed_records(memory_dir: Path) -> Iterator[MemoryRecord]:
    """Yield typed MemoryRecords from memory_dir.

    A file is 'typed' if it starts with '---\n' AND LattiMemoryStore.load()
    returns a non-None record. Anything else is silently skipped.
    """
    if not memory_dir.is_dir():
        return
    store = LattiMemoryStore(memory_dir)
    for path in sorted(memory_dir.glob('*.md')):
        if path.name == 'MEMORY.md':
            continue  # index file, not a record
        try:
            head = path.read_bytes()[:4]
        except OSError:
            continue
        if head != b'---\n':
            continue
        record = store.load(path)
        if record is not None:
            yield record


def load_typed_records_sorted(memory_dir: Path) -> list[MemoryRecord]:
    """Load typed records sorted by frontmatter last_used (oldest first).

    last_used in MemoryRecord is a Unix timestamp (float). Frontmatter
    stores it as date-string; LattiMemoryStore.load reconstructs the float
    from the date (midnight UTC of that date), so sort order is by date.
    """
    return sorted(load_typed_records(memory_dir), key=lambda r: r.last_used)


def compute_substrate_sha(memory_dir: Path) -> str:
    """SHA256 of all typed-record file contents, sorted by filename.

    Legacy (non-typed) files are excluded by the typed-only walk.
    Frontmatter last_used is date-granular, so same-day re-saves of a
    record produce identical file bytes → stable sha.
    """
    if not memory_dir.is_dir():
        return hashlib.sha256(b'').hexdigest()
    h = hashlib.sha256()
    for record_path in _typed_record_paths(memory_dir):
        h.update(record_path.read_bytes())
    return h.hexdigest()


def _typed_record_paths(memory_dir: Path) -> list[Path]:
    """Filenames of typed records in deterministic order."""
    if not memory_dir.is_dir():
        return []
    paths = []
    for path in sorted(memory_dir.glob('*.md')):
        if path.name == 'MEMORY.md':
            continue
        try:
            if path.read_bytes()[:4] == b'---\n':
                paths.append(path)
        except OSError:
            continue
    return paths


def render_where_section(active_goals: list, records: list[MemoryRecord]) -> str:
    """Render the templated WHERE section.

    active_goals: any object with .title, .status, .success_criteria attrs.
    records: typed MemoryRecords sorted oldest first.
    """
    if active_goals:
        goal_lines = '\n'.join(
            f'  - {g.title} — {g.status} — '
            f'{g.success_criteria[0] if g.success_criteria else "no criteria"}'
            for g in active_goals
        )
    else:
        goal_lines = PLACEHOLDER_NO_GOALS

    if records:
        last = records[-1]
        body_preview = last.body.replace('\n', ' ')[:80]
        last_record = (
            f'{last.kind} at {datetime.date.fromtimestamp(last.last_used).isoformat()} '
            f'— {body_preview}'
        )
        cutoff = max(r.last_used for r in records) - 86400  # 24h
        recent = [r for r in records if r.last_used >= cutoff]
        if recent:
            counts = Counter(r.kind for r in recent)
            recent_focus = ', '.join(f'{k}×{v}' for k, v in counts.most_common(3))
        else:
            recent_focus = '(no records in last 24h)'
    else:
        last_record = PLACEHOLDER_NO_RECORDS
        recent_focus = PLACEHOLDER_NO_RECORDS

    return WHERE_SECTION.format(
        n_goals=len(active_goals),
        goal_lines=goal_lines,
        last_record=last_record,
        recent_focus=recent_focus,
    )


def render_learning_section(scars: list[MemoryRecord],
                            lessons: list[MemoryRecord]) -> str:
    """Render the templated LEARNING section.

    Caller passes already-sliced lists (last 5 scars, last 3 lessons).
    """
    def _line(r: MemoryRecord) -> str:
        first_line = r.body.splitlines()[0] if r.body.strip() else '(empty)'
        ts = datetime.date.fromtimestamp(r.last_used).isoformat()
        return f'  - {first_line} ({ts})'

    scar_lines = '\n'.join(_line(s) for s in scars) if scars else PLACEHOLDER_NO_SCARS
    lesson_lines = '\n'.join(_line(l) for l in lessons) if lessons else PLACEHOLDER_NO_LESSONS
    return LEARNING_SECTION.format(scar_lines=scar_lines, lesson_lines=lesson_lines)


_BECOMING_RE = re.compile(
    r'<!-- BECOMING-SECTION-START -->\n(?P<body>.*?)\n<!-- BECOMING-SECTION-END -->',
    re.DOTALL,
)


def extract_becoming_section(identity_path: Path) -> str | None:
    """Return the contents between BECOMING-SECTION markers, or None."""
    if not identity_path.is_file():
        return None
    try:
        text = identity_path.read_text(encoding='utf-8')
    except OSError:
        return None
    m = _BECOMING_RE.search(text)
    return m.group('body') if m else None


def preserve_becoming_if_user_edited(identity_path: Path,
                                     last_compiled_at: float | None) -> str | None:
    """Return the existing becoming-section if the file is newer than last compile.

    If last_compiled_at is None (no prior compile) → return None (no preservation
    needed; daemon will write fresh).
    Returns None if no preservation should happen — daemon is free to regenerate.
    """
    if last_compiled_at is None:
        return None
    if not identity_path.is_file():
        return None
    if identity_path.stat().st_mtime > last_compiled_at:
        return extract_becoming_section(identity_path)
    return None


def render_identity_md(*, compiled_at: str, generation: int, substrate_sha: str,
                       prose_freshness: str, who_section: str, where_section: str,
                       learning_section: str, becoming_section: str) -> str:
    """Assemble the complete IDENTITY.md text from rendered sections."""
    return IDENTITY_MD.format(
        compiled_at=compiled_at,
        generation=generation,
        substrate_sha=substrate_sha,
        prose_freshness=prose_freshness,
        who_section=who_section.strip(),
        where_section=where_section.strip(),
        learning_section=learning_section.strip(),
        becoming_section=becoming_section.strip(),
    )


def write_identity_md_if_changed(target: Path, content: str,
                                 prior_sha: str | None) -> bool:
    """Atomically write content to target if its sha differs from prior_sha.

    Returns True if a write occurred, False if skipped (sha matched).
    """
    new_sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
    if prior_sha is not None and new_sha == prior_sha:
        return False
    tmp = target.with_suffix(target.suffix + '.tmp')
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding='utf-8')
    tmp.replace(target)
    return True
