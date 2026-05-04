"""ReadFileOperator refuses paths that match known secret-bearing conventions.

Pre-emptive guard at the operator layer. Redaction at ingestion is a
band-aid — refusing to read the file at all is the structural fix.
Bash retains the ability to read these paths with explicit intent.
"""
from __future__ import annotations

from pathlib import Path

from src.agent_state_machine import Action, State
from src.state_machine_operators import ReadFileOperator, _is_secret_bearing_path


def _exec(path: Path) -> dict:
    op = ReadFileOperator()
    state = State.fresh(session_id='read_guard', budget_usd=1.0)
    obs = op.execute(
        Action(kind='tool_call', payload={'tool_name': 'read_file', 'path': str(path)}),
        state,
    )
    return {'kind': obs.kind, 'payload': obs.payload}


def test_refuses_dotenv(tmp_path: Path):
    p = tmp_path / '.env'
    p.write_text('SECRET=abc')
    out = _exec(p)
    assert out['kind'] == 'error'
    assert out['payload']['refused_reason'] == 'secret_bearing_path'
    assert 'SECRET' not in str(out['payload'])  # contents never read


def test_refuses_dotenv_local(tmp_path: Path):
    p = tmp_path / '.env.local'
    p.write_text('SECRET=abc')
    assert _exec(p)['payload']['refused_reason'] == 'secret_bearing_path'


def test_refuses_pem(tmp_path: Path):
    p = tmp_path / 'id_rsa.pem'
    p.write_text('-----BEGIN RSA PRIVATE KEY-----')
    assert _exec(p)['payload']['refused_reason'] == 'secret_bearing_path'


def test_refuses_id_rsa(tmp_path: Path):
    p = tmp_path / 'id_rsa'
    p.write_text('key')
    assert _exec(p)['payload']['refused_reason'] == 'secret_bearing_path'


def test_refuses_credentials_json(tmp_path: Path):
    p = tmp_path / 'credentials.json'
    p.write_text('{"key":"v"}')
    assert _exec(p)['payload']['refused_reason'] == 'secret_bearing_path'


def test_refuses_dot_aws_credentials(tmp_path: Path):
    aws = tmp_path / '.aws'
    aws.mkdir()
    p = aws / 'credentials'
    p.write_text('[default]\naws_access_key_id=AKIAxxxx')
    assert _exec(p)['payload']['refused_reason'] == 'secret_bearing_path'


def test_allows_normal_text_file(tmp_path: Path):
    p = tmp_path / 'README.md'
    p.write_text('hello world')
    out = _exec(p)
    assert out['kind'] == 'success'
    assert out['payload']['content'] == 'hello world'


def test_allows_env_in_safe_filename(tmp_path: Path):
    """`.environment.md` should NOT be refused — the pattern is `.env` end-of-name
    or `.env.<ext>`, not the substring `env` anywhere.
    """
    p = tmp_path / 'environment.md'
    p.write_text('docs about env vars')
    assert _exec(p)['kind'] == 'success'


def test_pattern_match_helper_recognizes_path_segments():
    """Direct unit test on the helper — clearer failure mode than going
    through the operator.
    """
    assert _is_secret_bearing_path(Path('/home/u/project/.env'))
    assert _is_secret_bearing_path(Path('/home/u/.aws/credentials'))
    assert _is_secret_bearing_path(Path('/home/u/.ssh/id_ed25519'))
    assert not _is_secret_bearing_path(Path('/home/u/project/README.md'))
    assert not _is_secret_bearing_path(Path('/home/u/project/env_loader.py'))
