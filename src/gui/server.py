"""FastAPI server backing the local web GUI.

Wraps a single global :class:`LocalCodingAgent`, exposes JSON endpoints for
chat, slash commands, and saved sessions, and serves the static SPA.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


# Sentinel for "field not provided" — lets callers distinguish "leave as-is"
# from "set explicitly to None" (needed for budget knobs where None means
# unlimited, which is itself a valid setting the user may want to apply).
_UNSET: Any = object()

from ..agent_runtime import LocalCodingAgent
from ..agent_slash_commands import get_slash_command_specs
from ..agent_types import (
    AgentPermissions,
    AgentRuntimeConfig,
    BudgetConfig,
    ModelConfig,
)
from ..bundled_skills import get_bundled_skills
from ..paste_refs import PastedContent, expand_pasted_text_refs
from ..session_store import (
    DEFAULT_AGENT_SESSION_DIR,
    StoredAgentSession,
    load_agent_session,
)


STATIC_DIR = Path(__file__).parent / 'static'


# ---------------------------------------------------------------------------
# Agent state holder
# ---------------------------------------------------------------------------

class AgentState:
    """Holds the live agent instance plus a lock for serialized access."""

    def __init__(
        self,
        *,
        cwd: Path,
        model: str,
        base_url: str,
        api_key: str,
        allow_shell: bool,
        allow_write: bool,
        session_directory: Path,
        temperature: float = 0.0,
        timeout_seconds: float = 120.0,
        stream_model_responses: bool = False,
        max_turns: int = 12,
        max_total_tokens: int | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        max_reasoning_tokens: int | None = None,
        max_total_cost_usd: float | None = None,
        max_tool_calls: int | None = None,
        max_delegated_tasks: int | None = None,
        max_model_calls: int | None = None,
        max_session_turns: int | None = None,
    ) -> None:
        self.cwd = cwd.resolve()
        self.session_directory = session_directory
        self._lock = Lock()
        self._agent: LocalCodingAgent | None = None
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.allow_shell = allow_shell
        self.allow_write = allow_write
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.stream_model_responses = stream_model_responses
        self.max_turns = max_turns
        self.max_total_tokens = max_total_tokens
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_reasoning_tokens = max_reasoning_tokens
        self.max_total_cost_usd = max_total_cost_usd
        self.max_tool_calls = max_tool_calls
        self.max_delegated_tasks = max_delegated_tasks
        self.max_model_calls = max_model_calls
        self.max_session_turns = max_session_turns
        self._build_agent()

    def _build_agent(self) -> None:
        permissions = AgentPermissions(
            allow_file_write=self.allow_write,
            allow_shell_commands=self.allow_shell,
        )
        budget_config = BudgetConfig(
            max_total_tokens=self.max_total_tokens,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
            max_reasoning_tokens=self.max_reasoning_tokens,
            max_total_cost_usd=self.max_total_cost_usd,
            max_tool_calls=self.max_tool_calls,
            max_delegated_tasks=self.max_delegated_tasks,
            max_model_calls=self.max_model_calls,
            max_session_turns=self.max_session_turns,
        )
        runtime_config = AgentRuntimeConfig(
            cwd=self.cwd,
            permissions=permissions,
            session_directory=self.session_directory,
            stream_model_responses=self.stream_model_responses,
            max_turns=self.max_turns,
            budget_config=budget_config,
        )
        model_config = ModelConfig(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
        )
        self._agent = LocalCodingAgent(
            model_config=model_config,
            runtime_config=runtime_config,
        )

    @property
    def agent(self) -> LocalCodingAgent:
        assert self._agent is not None
        return self._agent

    def update(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        cwd: str | None = None,
        allow_shell: bool | None = None,
        allow_write: bool | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        stream_model_responses: bool | None = None,
        max_turns: int | None = None,
        # Budget knobs use the sentinel pattern — `None` means "no limit"
        # (a valid setting), so they need a distinct "not provided" marker.
        max_total_tokens: Any = _UNSET,
        max_input_tokens: Any = _UNSET,
        max_output_tokens: Any = _UNSET,
        max_reasoning_tokens: Any = _UNSET,
        max_total_cost_usd: Any = _UNSET,
        max_tool_calls: Any = _UNSET,
        max_delegated_tasks: Any = _UNSET,
        max_model_calls: Any = _UNSET,
        max_session_turns: Any = _UNSET,
    ) -> None:
        with self._lock:
            if model is not None:
                self.model = model
            if base_url is not None:
                self.base_url = base_url
            if api_key is not None:
                self.api_key = api_key
            if cwd is not None:
                resolved = Path(cwd).expanduser().resolve()
                if not resolved.is_dir():
                    raise ValueError(f'cwd does not exist: {resolved}')
                self.cwd = resolved
            if allow_shell is not None:
                self.allow_shell = allow_shell
            if allow_write is not None:
                self.allow_write = allow_write
            if temperature is not None:
                if temperature < 0:
                    raise ValueError('temperature must be >= 0')
                self.temperature = temperature
            if timeout_seconds is not None:
                if timeout_seconds <= 0:
                    raise ValueError('timeout_seconds must be > 0')
                self.timeout_seconds = timeout_seconds
            if stream_model_responses is not None:
                self.stream_model_responses = stream_model_responses
            if max_turns is not None:
                if max_turns < 1:
                    raise ValueError('max_turns must be >= 1')
                self.max_turns = max_turns

            for name, value, kind in (
                ('max_total_tokens', max_total_tokens, 'int'),
                ('max_input_tokens', max_input_tokens, 'int'),
                ('max_output_tokens', max_output_tokens, 'int'),
                ('max_reasoning_tokens', max_reasoning_tokens, 'int'),
                ('max_total_cost_usd', max_total_cost_usd, 'float'),
                ('max_tool_calls', max_tool_calls, 'int'),
                ('max_delegated_tasks', max_delegated_tasks, 'int'),
                ('max_model_calls', max_model_calls, 'int'),
                ('max_session_turns', max_session_turns, 'int'),
            ):
                if value is _UNSET:
                    continue
                if value is not None:
                    if (kind == 'int' and (not isinstance(value, int) or isinstance(value, bool))) or (
                        kind == 'float' and not isinstance(value, (int, float))
                    ):
                        raise ValueError(f'{name} must be a number or null')
                    if value <= 0:
                        raise ValueError(f'{name} must be > 0 or null')
                setattr(self, name, value)

            self._build_agent()

    def snapshot(self) -> dict[str, Any]:
        return {
            'model': self.model,
            'base_url': self.base_url,
            'cwd': str(self.cwd),
            'session_directory': str(self.session_directory),
            'allow_shell': self.allow_shell,
            'allow_write': self.allow_write,
            'temperature': self.temperature,
            'timeout_seconds': self.timeout_seconds,
            'stream_model_responses': self.stream_model_responses,
            'max_turns': self.max_turns,
            'max_total_tokens': self.max_total_tokens,
            'max_input_tokens': self.max_input_tokens,
            'max_output_tokens': self.max_output_tokens,
            'max_reasoning_tokens': self.max_reasoning_tokens,
            'max_total_cost_usd': self.max_total_cost_usd,
            'max_tool_calls': self.max_tool_calls,
            'max_delegated_tasks': self.max_delegated_tasks,
            'max_model_calls': self.max_model_calls,
            'max_session_turns': self.max_session_turns,
            'active_session_id': self.agent.active_session_id,
        }

    def lock(self) -> Lock:
        return self._lock


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PastedContentPayload(BaseModel):
    """JSON shape for an entry in :class:`ChatRequest.pasted_contents`.

    Mirrors :class:`src.paste_refs.PastedContent` minus the id (the dict key
    in the parent payload).  ``type`` is constrained to ``text`` for now —
    image expansion isn't wired into the agent runtime yet.
    """

    type: str = Field(default='text')
    content: str
    media_type: str | None = None
    filename: str | None = None


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    resume_session_id: str | None = None
    pasted_contents: dict[int, PastedContentPayload] = Field(default_factory=dict)


class StateUpdate(BaseModel):
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    cwd: str | None = None
    allow_shell: bool | None = None
    allow_write: bool | None = None
    temperature: float | None = None
    timeout_seconds: float | None = None
    stream_model_responses: bool | None = None
    max_turns: int | None = None
    # Budget knobs — null clears the limit, omitted leaves it untouched.
    max_total_tokens: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_reasoning_tokens: int | None = None
    max_total_cost_usd: float | None = None
    max_tool_calls: int | None = None
    max_delegated_tasks: int | None = None
    max_model_calls: int | None = None
    max_session_turns: int | None = None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(state: AgentState) -> FastAPI:
    app = FastAPI(title='Claw Code GUI', version='1.0')

    # ------------- static + index ------------------------------------------
    app.mount(
        '/static',
        StaticFiles(directory=str(STATIC_DIR)),
        name='static',
    )

    @app.get('/', include_in_schema=False)
    async def root() -> FileResponse:
        return FileResponse(STATIC_DIR / 'index.html')

    # ------------- info ------------------------------------------------------
    @app.get('/api/state')
    async def get_state() -> dict[str, Any]:
        return state.snapshot()

    @app.post('/api/state')
    async def post_state(payload: StateUpdate) -> dict[str, Any]:
        try:
            # exclude_unset preserves explicit null (e.g. "clear the limit")
            # while omitting fields the client never mentioned.
            state.update(**payload.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return state.snapshot()

    @app.get('/api/slash-commands')
    async def list_slash_commands() -> list[dict[str, Any]]:
        commands: list[dict[str, Any]] = []
        for spec in get_slash_command_specs():
            commands.append(
                {
                    'names': list(spec.names),
                    'primary': spec.names[0],
                    'description': spec.description,
                }
            )
        return commands

    @app.get('/api/skills')
    async def list_skills() -> list[dict[str, Any]]:
        return [
            {
                'name': skill.name,
                'description': skill.description,
                'when_to_use': skill.when_to_use,
                'aliases': list(skill.aliases),
                'allowed_tools': list(skill.allowed_tools),
            }
            for skill in get_bundled_skills()
            if skill.user_invocable
        ]

    # ------------- sessions --------------------------------------------------
    @app.get('/api/sessions')
    async def list_sessions() -> list[dict[str, Any]]:
        directory = state.session_directory
        if not directory.exists():
            return []
        results: list[dict[str, Any]] = []
        for path in sorted(
            directory.glob('*.json'),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                continue
            messages = data.get('messages') or []
            preview = ''
            for msg in messages:
                if isinstance(msg, dict) and msg.get('role') == 'user':
                    content = msg.get('content', '')
                    if isinstance(content, str):
                        preview = content[:120]
                        break
            results.append(
                {
                    'session_id': data.get('session_id', path.stem),
                    'turns': data.get('turns', 0),
                    'tool_calls': data.get('tool_calls', 0),
                    'preview': preview,
                    'modified_at': path.stat().st_mtime,
                }
            )
        return results

    @app.get('/api/sessions/{session_id}')
    async def get_session(session_id: str) -> dict[str, Any]:
        try:
            stored = load_agent_session(session_id, directory=state.session_directory)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail='Session not found')
        return _serialize_stored_session(stored)

    # ------------- chat ------------------------------------------------------
    @app.post('/api/chat')
    async def chat(request: ChatRequest) -> dict[str, Any]:
        prompt = request.prompt.strip()
        if not prompt:
            raise HTTPException(status_code=400, detail='Prompt is empty')

        if request.pasted_contents:
            store = {
                ref_id: PastedContent(
                    id=ref_id,
                    type=payload.type,
                    content=payload.content,
                    media_type=payload.media_type,
                    filename=payload.filename,
                )
                for ref_id, payload in request.pasted_contents.items()
            }
            prompt = expand_pasted_text_refs(prompt, store)

        def _run() -> dict[str, Any]:
            with state.lock():
                agent = state.agent
                if request.resume_session_id is not None:
                    try:
                        stored = load_agent_session(
                            request.resume_session_id,
                            directory=state.session_directory,
                        )
                    except FileNotFoundError:
                        raise HTTPException(
                            status_code=404,
                            detail='Session to resume not found',
                        )
                    result = agent.resume(prompt, stored)
                else:
                    result = agent.run(prompt)
                return _serialize_run_result(result)

        try:
            payload = await asyncio.to_thread(_run)
        except HTTPException:
            raise
        except Exception as exc:  # surface the error in the UI
            return JSONResponse(
                status_code=500,
                content={
                    'error': str(exc),
                    'error_type': type(exc).__name__,
                },
            )
        return payload

    @app.post('/api/clear')
    async def clear_state() -> dict[str, Any]:
        with state.lock():
            state.agent.clear_runtime_state()
        return state.snapshot()

    return app


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_run_result(result: Any) -> dict[str, Any]:
    return {
        'final_output': result.final_output,
        'turns': result.turns,
        'tool_calls': result.tool_calls,
        'transcript': [_normalize_transcript_entry(entry) for entry in result.transcript],
        'session_id': result.session_id,
        'usage': result.usage.to_dict(),
        'total_cost_usd': result.total_cost_usd,
        'stop_reason': result.stop_reason,
    }


def _normalize_transcript_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        'role': entry.get('role', ''),
        'content': entry.get('content', ''),
    }
    for key in ('name', 'tool_call_id', 'tool_calls', 'metadata', 'message_id'):
        if key in entry and entry[key] not in (None, '', [], {}):
            out[key] = entry[key]
    return out


def _serialize_stored_session(stored: StoredAgentSession) -> dict[str, Any]:
    return {
        'session_id': stored.session_id,
        'turns': stored.turns,
        'tool_calls': stored.tool_calls,
        'messages': [_normalize_transcript_entry(dict(m)) for m in stored.messages],
        'usage': stored.usage,
        'total_cost_usd': stored.total_cost_usd,
        'model': stored.model_config.get('model'),
    }
