# src/identity_compile.py
"""Compile Latti's typed substrate into IDENTITY.md (now-file) + HISTORY.md.

See docs/superpowers/specs/2026-05-01-latti-self-writing-identity-design.md.

Substrate read is *typed-only*: file must start with '---\n' AND parse via
LattiMemoryStore.load(). Legacy markdown files in ~/.latti/memory/ are
invisible to identity by design (~98% are operational debris).
"""
from __future__ import annotations

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
