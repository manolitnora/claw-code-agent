# src/identity_compile.py
"""Compile Latti's typed substrate into IDENTITY.md (now-file) + HISTORY.md.

See docs/superpowers/specs/2026-05-01-latti-self-writing-identity-design.md.

Substrate read is *typed-only*: file must start with '---\n' AND parse via
LattiMemoryStore.load(). Legacy markdown files in ~/.latti/memory/ are
invisible to identity by design (~98% are operational debris).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

from src.agent_state_machine import MemoryRecord
from src.state_machine_memory import LattiMemoryStore


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
