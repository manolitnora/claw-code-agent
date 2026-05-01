# tests/test_identity_compile.py
"""Tests for identity_compile.

The compiler reads typed MemoryRecord files from a memory directory and
produces ~/.latti/IDENTITY.md (now-file) + ~/.latti/HISTORY.md (history).
All tests use tmp_path; no test touches the real ~/.latti/.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _write_typed_record(memory_dir: Path, kind: str, slug: str, body: str,
                        last_used: str = '2026-05-01') -> Path:
    """Write a typed MemoryRecord file directly (matches LattiMemoryStore format)."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = memory_dir / f'{kind}_{slug}.md'
    path.write_text(
        f'---\n'
        f'name: {slug}\n'
        f'description: test record\n'
        f'type: {kind}\n'
        f'id: mem_{slug}\n'
        f'last_used: {last_used}\n'
        f'---\n'
        f'{body}\n',
        encoding='utf-8',
    )
    return path


def _write_legacy_file(memory_dir: Path, name: str, body: str) -> Path:
    """Write a no-frontmatter legacy file (must be invisible to compiler)."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = memory_dir / name
    path.write_text(body, encoding='utf-8')
    return path


def test_load_typed_records_filters_legacy(tmp_path):
    from src.identity_compile import load_typed_records

    mem = tmp_path / 'memory'
    _write_typed_record(mem, 'scar', 'first', 'first scar body')
    _write_typed_record(mem, 'lesson', 'second', 'second lesson body')
    _write_legacy_file(mem, 'AUDIT_DUMP.md', 'unstructured audit output')
    _write_legacy_file(mem, 'BOOT_LOG.txt', 'boot log')

    records = list(load_typed_records(mem))
    kinds = sorted(r.kind for r in records)
    assert kinds == ['lesson', 'scar']
    assert all(r.id.startswith('mem_') for r in records)


def test_load_typed_records_skips_unparseable_typed_files(tmp_path):
    from src.identity_compile import load_typed_records

    mem = tmp_path / 'memory'
    _write_typed_record(mem, 'scar', 'good', 'body')
    # Looks typed (starts with ---) but malformed frontmatter
    (mem / 'scar_broken.md').write_text(
        '---\nthis is not valid: yaml: like: at all:\n', encoding='utf-8',
    )

    records = list(load_typed_records(mem))
    assert len(records) == 1
    assert records[0].id == 'mem_good'


def test_load_typed_records_empty_dir(tmp_path):
    from src.identity_compile import load_typed_records
    records = list(load_typed_records(tmp_path / 'nonexistent'))
    assert records == []
