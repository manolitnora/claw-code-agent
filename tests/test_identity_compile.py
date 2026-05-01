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


def test_records_sorted_by_frontmatter_not_mtime(tmp_path):
    """Sort key is frontmatter last_used, NOT filesystem mtime."""
    import os
    import time
    from src.identity_compile import load_typed_records_sorted

    mem = tmp_path / 'memory'
    p_old = _write_typed_record(mem, 'scar', 'old', 'old', last_used='2026-04-01')
    p_new = _write_typed_record(mem, 'scar', 'new', 'new', last_used='2026-05-01')
    # Touch the OLD file so its mtime is newest
    new_mtime = time.time()
    os.utime(p_old, (new_mtime, new_mtime))
    os.utime(p_new, (new_mtime - 86400, new_mtime - 86400))

    records = list(load_typed_records_sorted(mem))
    # Should be sorted oldest first by frontmatter date
    assert [r.id for r in records] == ['mem_old', 'mem_new']


def test_substrate_sha_stable_across_identical_compiles(tmp_path):
    """Two consecutive sha computations on unchanged files → same sha."""
    from src.identity_compile import compute_substrate_sha

    mem = tmp_path / 'memory'
    _write_typed_record(mem, 'scar', 'a', 'body a')
    _write_typed_record(mem, 'lesson', 'b', 'body b')

    sha1 = compute_substrate_sha(mem)
    sha2 = compute_substrate_sha(mem)
    assert sha1 == sha2
    assert len(sha1) == 64  # sha256 hex


def test_substrate_sha_changes_when_record_added(tmp_path):
    from src.identity_compile import compute_substrate_sha

    mem = tmp_path / 'memory'
    _write_typed_record(mem, 'scar', 'a', 'body a')
    sha1 = compute_substrate_sha(mem)

    _write_typed_record(mem, 'lesson', 'b', 'body b')
    sha2 = compute_substrate_sha(mem)
    assert sha1 != sha2


def test_substrate_sha_ignores_legacy_files(tmp_path):
    from src.identity_compile import compute_substrate_sha

    mem = tmp_path / 'memory'
    _write_typed_record(mem, 'scar', 'a', 'body')
    sha1 = compute_substrate_sha(mem)

    _write_legacy_file(mem, 'AUDIT.md', 'audit junk')
    sha2 = compute_substrate_sha(mem)
    assert sha1 == sha2  # legacy file does not affect sha


def test_where_section_with_no_records(tmp_path):
    from src.identity_compile import render_where_section
    out = render_where_section(active_goals=[], records=[])
    assert '## where I am' in out
    assert '0 typed records yet' in out
    assert 'Active goals' in out
    assert '(no active goals)' in out


def test_where_section_with_goals_and_records(tmp_path):
    from src.identity_compile import render_where_section
    from src.identity_compile import load_typed_records_sorted

    mem = tmp_path / 'memory'
    _write_typed_record(mem, 'scar', 'a', 'first scar')
    _write_typed_record(mem, 'lesson', 'b', 'a lesson')
    records = load_typed_records_sorted(mem)

    class FakeGoal:
        title = 'directive compliance ≥ 0.7'
        status = 'active'
        success_criteria = ('5 consecutive sessions',)

    out = render_where_section(active_goals=[FakeGoal()], records=records)
    assert 'directive compliance' in out
    assert 'active' in out
    assert 'lesson' in out  # last record kind
    assert '5 consecutive sessions' in out
