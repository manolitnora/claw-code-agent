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


def test_learning_section_empty(tmp_path):
    from src.identity_compile import render_learning_section
    out = render_learning_section(scars=[], lessons=[])
    assert '## what I\'m learning' in out
    assert '(no scars recorded)' in out
    assert '(no lessons recorded)' in out


def test_learning_section_with_records(tmp_path):
    from src.identity_compile import render_learning_section, load_typed_records_sorted

    mem = tmp_path / 'memory'
    _write_typed_record(mem, 'scar', 'first', 'first scar body line\nmore lines')
    _write_typed_record(mem, 'scar', 'second', 'second scar body')
    _write_typed_record(mem, 'lesson', 'l1', 'a lesson')
    records = load_typed_records_sorted(mem)
    scars = [r for r in records if r.kind == 'scar']
    lessons = [r for r in records if r.kind == 'lesson']

    out = render_learning_section(scars=scars, lessons=lessons)
    assert 'first scar body line' in out  # only first line, no \n
    assert 'second scar body' in out
    assert 'a lesson' in out


def test_learning_section_caps_at_5_scars_3_lessons(tmp_path):
    from src.identity_compile import render_learning_section
    from src.agent_state_machine import MemoryRecord

    scars = [MemoryRecord.new('scar', f'scar body {i}') for i in range(10)]
    lessons = [MemoryRecord.new('lesson', f'lesson body {i}') for i in range(10)]
    out = render_learning_section(scars=scars[-5:], lessons=lessons[-3:])
    assert out.count('  - scar body') == 5
    assert out.count('  - lesson body') == 3


def test_becoming_section_extracted_from_existing_identity(tmp_path):
    from src.identity_compile import extract_becoming_section

    identity_path = tmp_path / 'IDENTITY.md'
    identity_path.write_text(
        '## who I am\nstuff\n\n'
        '## who I\'m becoming\n'
        '<!-- BECOMING-SECTION-START -->\n'
        'I want to become better at noticing my own drift.\n'
        '<!-- BECOMING-SECTION-END -->\n',
        encoding='utf-8',
    )
    out = extract_becoming_section(identity_path)
    assert out is not None
    assert 'better at noticing my own drift' in out


def test_becoming_section_extract_returns_none_if_no_file(tmp_path):
    from src.identity_compile import extract_becoming_section
    out = extract_becoming_section(tmp_path / 'missing.md')
    assert out is None


def test_becoming_section_extract_returns_none_if_no_markers(tmp_path):
    from src.identity_compile import extract_becoming_section
    p = tmp_path / 'IDENTITY.md'
    p.write_text('## who I am\nbody\n', encoding='utf-8')
    out = extract_becoming_section(p)
    assert out is None


def test_becoming_section_preserved_when_user_edited_after_compile(tmp_path):
    from src.identity_compile import preserve_becoming_if_user_edited

    p = tmp_path / 'IDENTITY.md'
    p.write_text(
        '## who I\'m becoming\n'
        '<!-- BECOMING-SECTION-START -->\n'
        'user edit\n'
        '<!-- BECOMING-SECTION-END -->\n',
        encoding='utf-8',
    )
    file_mtime = p.stat().st_mtime
    out = preserve_becoming_if_user_edited(p, last_compiled_at=file_mtime - 10)
    assert out is not None
    assert 'user edit' in out


def test_becoming_section_not_preserved_when_compile_is_newer(tmp_path):
    from src.identity_compile import preserve_becoming_if_user_edited

    p = tmp_path / 'IDENTITY.md'
    p.write_text('## who I\'m becoming\n<!-- BECOMING-SECTION-START -->\nx\n<!-- BECOMING-SECTION-END -->\n', encoding='utf-8')
    file_mtime = p.stat().st_mtime
    out = preserve_becoming_if_user_edited(p, last_compiled_at=file_mtime + 10)
    assert out is None


def test_render_identity_md_assembles_all_sections(tmp_path):
    from src.identity_compile import render_identity_md

    out = render_identity_md(
        compiled_at='2026-05-01T00:00:00Z',
        generation=1,
        substrate_sha='abc123',
        prose_freshness='live',
        who_section='I am Latti.',
        where_section='## where I am\nstuff\n',
        learning_section='## what I\'m learning\nstuff\n',
        becoming_section='I want to grow.',
    )
    assert out.startswith('---\n')
    assert 'compiled_at: 2026-05-01T00:00:00Z' in out
    assert 'generation: 1' in out
    assert 'substrate_sha: abc123' in out
    assert 'prose_freshness: live' in out
    assert '## who I am\nI am Latti.' in out
    assert '## where I am' in out
    assert '## what I\'m learning' in out
    assert '<!-- BECOMING-SECTION-START -->' in out
    assert 'I want to grow.' in out
    assert '<!-- BECOMING-SECTION-END -->' in out
    assert 'pointers' in out


def test_atomic_write_sha_gated_skips_when_unchanged(tmp_path):
    from src.identity_compile import write_identity_md_if_changed

    target = tmp_path / 'IDENTITY.md'
    content = '# hello\n'
    written1 = write_identity_md_if_changed(target, content, prior_sha=None)
    assert written1 is True
    mtime1 = target.stat().st_mtime

    import time; time.sleep(0.01)
    import hashlib
    sha = hashlib.sha256(content.encode()).hexdigest()
    written2 = write_identity_md_if_changed(target, content, prior_sha=sha)
    assert written2 is False
    assert target.stat().st_mtime == mtime1


def test_atomic_write_writes_when_content_differs(tmp_path):
    from src.identity_compile import write_identity_md_if_changed

    target = tmp_path / 'IDENTITY.md'
    write_identity_md_if_changed(target, 'content v1\n', prior_sha=None)
    written = write_identity_md_if_changed(target, 'content v2\n', prior_sha='wrong-sha')
    assert written is True
    assert target.read_text() == 'content v2\n'


def test_render_history_entry_includes_kind_id_body(tmp_path):
    from src.identity_compile import render_history_entries
    from src.agent_state_machine import MemoryRecord

    rec = MemoryRecord.new('scar', 'a scar happened\nmore detail')
    out = render_history_entries([rec])
    assert '· scar' in out
    assert rec.id in out
    assert 'a scar happened' in out


def test_load_cursor_returns_zero_when_file_absent(tmp_path):
    from src.identity_compile import load_cursor
    cur = load_cursor(tmp_path / 'no-cursor')
    assert cur == {'last_ts': 0.0, 'last_id': None}


def test_save_then_load_cursor_roundtrip(tmp_path):
    from src.identity_compile import load_cursor, save_cursor
    p = tmp_path / 'cursor.json'
    save_cursor(p, {'last_ts': 1234.5, 'last_id': 'mem_xyz'})
    cur = load_cursor(p)
    assert cur['last_ts'] == 1234.5
    assert cur['last_id'] == 'mem_xyz'


def test_history_appends_only_new_records(tmp_path):
    from src.identity_compile import (
        load_typed_records_sorted, append_new_records_to_history,
    )

    mem = tmp_path / 'memory'
    _write_typed_record(mem, 'scar', 'first', 'first', last_used='2026-04-01')
    _write_typed_record(mem, 'scar', 'second', 'second', last_used='2026-04-02')

    history = tmp_path / 'HISTORY.md'
    cursor_path = tmp_path / '.history-cursor'

    appended1 = append_new_records_to_history(
        history_path=history, cursor_path=cursor_path,
        records=load_typed_records_sorted(mem),
    )
    assert appended1 == 2
    assert 'first' in history.read_text()
    assert 'second' in history.read_text()

    appended2 = append_new_records_to_history(
        history_path=history, cursor_path=cursor_path,
        records=load_typed_records_sorted(mem),
    )
    assert appended2 == 0
    body_size = history.stat().st_size

    _write_typed_record(mem, 'lesson', 'third', 'third', last_used='2026-04-03')
    appended3 = append_new_records_to_history(
        history_path=history, cursor_path=cursor_path,
        records=load_typed_records_sorted(mem),
    )
    assert appended3 == 1
    assert history.stat().st_size > body_size
    assert 'third' in history.read_text()


def test_ollama_call_returns_response_text(tmp_path):
    import urllib.error
    from unittest.mock import patch
    from src.identity_compile import call_ollama

    fake_response = b'{"response": "hello world", "eval_count": 2}'
    with patch('src.identity_compile._ollama_post', return_value=fake_response):
        out = call_ollama(
            base_url='http://localhost:11434',
            model='gemma:latest',
            prompt='test',
            temperature=0.4,
            num_predict=10,
            timeout=5,
        )
    assert out == 'hello world'


def test_ollama_call_returns_none_on_connection_error(tmp_path):
    import urllib.error
    from unittest.mock import patch
    from src.identity_compile import call_ollama

    def boom(*a, **kw):
        raise urllib.error.URLError('connection refused')

    with patch('src.identity_compile._ollama_post', side_effect=boom):
        out = call_ollama(
            base_url='http://localhost:11434', model='gemma:latest',
            prompt='test', temperature=0.4, num_predict=10, timeout=5,
        )
    assert out is None


def test_ollama_call_returns_none_on_timeout(tmp_path):
    import socket
    from unittest.mock import patch
    from src.identity_compile import call_ollama

    with patch('src.identity_compile._ollama_post', side_effect=socket.timeout()):
        out = call_ollama(
            base_url='http://localhost:11434', model='gemma:latest',
            prompt='test', temperature=0.4, num_predict=10, timeout=5,
        )
    assert out is None


def test_ollama_call_returns_none_on_malformed_json(tmp_path):
    from unittest.mock import patch
    from src.identity_compile import call_ollama

    with patch('src.identity_compile._ollama_post', return_value=b'not json'):
        out = call_ollama(
            base_url='http://localhost:11434', model='gemma:latest',
            prompt='test', temperature=0.4, num_predict=10, timeout=5,
        )
    assert out is None
