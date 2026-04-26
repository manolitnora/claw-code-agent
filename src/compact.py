"""Conversation compaction service.

Mirrors the npm ``src/services/compact/compact.ts`` and
``src/services/compact/prompt.ts`` modules.  Provides:

- The 9-section summarisation prompt (``get_compact_prompt``).
- XML-tag formatting/stripping  (``format_compact_summary``).
- The post-compact user summary message builder
  (``get_compact_user_summary_message``).
- The core ``compact_conversation`` entry point that an
  ``/compact`` slash command or auto-compact subsystem can call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .agent_context_usage import estimate_tokens
from .agent_types import UsageStats
from .agent_session import AgentMessage

if TYPE_CHECKING:
    from .agent_runtime import LocalCodingAgent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUTOCOMPACT_BUFFER_TOKENS = 13_000
"""How many tokens to reserve below the effective context window before
auto-compact fires (same as the npm ``AUTOCOMPACT_BUFFER_TOKENS``)."""

ERROR_NOT_ENOUGH_MESSAGES = 'Not enough messages to compact.'
ERROR_INCOMPLETE_RESPONSE = (
    'The summary response was incomplete.  '
    'The conversation was not compacted.'
)
ERROR_USER_ABORT = 'Compaction canceled.'

MAX_COMPACT_FAILURES = 3
"""Circuit-breaker – stop retrying auto-compact after this many consecutive
failures (mirrors the npm implementation)."""

# ---------------------------------------------------------------------------
# Prompt construction  (npm ``src/services/compact/prompt.ts``)
# ---------------------------------------------------------------------------

_NO_TOOLS_PREAMBLE = """\
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

"""

_DETAILED_ANALYSIS_INSTRUCTION = """\
Before providing your final summary, wrap your analysis in <analysis> tags to \
organize your thoughts and ensure you've covered all necessary points. In your \
analysis process:

1. Chronologically analyze each message and section of the conversation. \
For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, \
especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each \
required element thoroughly."""

_BASE_COMPACT_PROMPT = f"""\
Your task is to create a detailed summary of the conversation so far, paying \
close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, \
and architectural decisions that would be essential for continuing development \
work without losing context.

{_DETAILED_ANALYSIS_INSTRUCTION}

Your summary should include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests \
and intents in detail
2. Key Technical Concepts: List all important technical concepts, technologies, \
and frameworks discussed.
3. Files and Code Sections: Enumerate specific files and code sections examined, \
modified, or created. Pay special attention to the most recent messages and \
include full code snippets where applicable and include a summary of why this \
file read or edit is important.
4. Errors and fixes: List all errors that you ran into, and how you fixed them. \
Pay special attention to specific user feedback that you received, especially if \
the user told you to do something differently.
5. Problem Solving: Document problems solved and any ongoing troubleshooting \
efforts.
6. All user messages: List ALL user messages that are not tool results. These \
are critical for understanding the users' feedback and changing intent.
7. Pending Tasks: Outline any pending tasks that you have explicitly been asked \
to work on.
8. Current Work: Describe in detail precisely what was being worked on \
immediately before this summary request, paying special attention to the most \
recent messages from both user and assistant. Include file names and code \
snippets where applicable.
9. Optional Next Step: List the next step that you will take that is related to \
the most recent work you were doing. IMPORTANT: ensure that this step is \
DIRECTLY in line with the user's most recent explicit requests, and the task \
you were working on immediately before this summary request. If your last task \
was concluded, then only list next steps if they are explicitly in line with the \
users request. Do not start on tangential requests or really old requests that \
were already completed without confirming with the user first.
                       If there is a next step, include direct quotes from the \
most recent conversation showing exactly what task you were working on and where \
you left off. This should be verbatim to ensure there's no drift in task \
interpretation.

Here's an example of how your output should be structured:

<example>
<analysis>
[Your thought process, ensuring all points are covered thoroughly and accurately]
</analysis>

<summary>
1. Primary Request and Intent:
   [Detailed description]

2. Key Technical Concepts:
   - [Concept 1]
   - [Concept 2]
   - [...]

3. Files and Code Sections:
   - [File Name 1]
      - [Summary of why this file is important]
      - [Summary of the changes made to this file, if any]
      - [Important Code Snippet]
   - [File Name 2]
      - [Important Code Snippet]
   - [...]

4. Errors and fixes:
    - [Detailed description of error 1]:
      - [How you fixed the error]
      - [User feedback on the error if any]
    - [...]

5. Problem Solving:
   [Description of solved problems and ongoing troubleshooting]

6. All user messages:
    - [Detailed non tool use user message]
    - [...]

7. Pending Tasks:
   - [Task 1]
   - [Task 2]
   - [...]

8. Current Work:
   [Precise description of current work]

9. Optional Next Step:
   [Optional Next step to take]

</summary>
</example>

Please provide your summary based on the conversation so far, following this \
structure and ensuring precision and thoroughness in your response.

There may be additional summarization instructions provided in the included \
context. If so, remember to follow these instructions when creating the above \
summary. Examples of instructions include:
<example>
## Compact Instructions
When summarizing the conversation focus on typescript code changes and also \
remember the mistakes you made and how you fixed them.
</example>

<example>
# Summary instructions
When you are using compact - please focus on test output and code changes. \
Include file reads verbatim.
</example>
"""

_NO_TOOLS_TRAILER = (
    '\n\nREMINDER: Do NOT call any tools. Respond with plain text only — '
    'an <analysis> block followed by a <summary> block. '
    'Tool calls will be rejected and you will fail the task.'
)


def get_compact_prompt(custom_instructions: str | None = None) -> str:
    """Build the full compact prompt, optionally appending user instructions."""
    prompt = _NO_TOOLS_PREAMBLE + _BASE_COMPACT_PROMPT
    if custom_instructions and custom_instructions.strip():
        prompt += f'\n\nAdditional Instructions:\n{custom_instructions}'
    prompt += _NO_TOOLS_TRAILER
    return prompt


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------

def format_compact_summary(summary: str) -> str:
    """Strip the ``<analysis>`` scratchpad and unwrap ``<summary>`` tags.

    Mirrors the npm ``formatCompactSummary`` helper.
    """
    formatted = re.sub(r'<analysis>[\s\S]*?</analysis>', '', summary)

    match = re.search(r'<summary>([\s\S]*?)</summary>', formatted)
    if match:
        content = match.group(1).strip()
        formatted = re.sub(
            r'<summary>[\s\S]*?</summary>',
            f'Summary:\n{content}',
            formatted,
        )

    # Collapse runs of blank lines.
    formatted = re.sub(r'\n\n+', '\n\n', formatted)
    return formatted.strip()


def get_compact_user_summary_message(
    summary: str,
    *,
    suppress_follow_up: bool = False,
    transcript_path: str | None = None,
) -> str:
    """Build the user-facing summary that replaces compacted messages.

    Mirrors the npm ``getCompactUserSummaryMessage`` helper.
    """
    formatted = format_compact_summary(summary)

    base = (
        'This session is being continued from a previous conversation that '
        'ran out of context. The summary below covers the earlier portion '
        f'of the conversation.\n\n{formatted}'
    )

    if transcript_path:
        base += (
            '\n\nIf you need specific details from before compaction '
            '(like exact code snippets, error messages, or content you '
            'generated), read the full transcript at: '
            f'{transcript_path}'
        )

    if suppress_follow_up:
        base += (
            '\nContinue the conversation from where it left off without '
            'asking the user any further questions. Resume directly — do '
            'not acknowledge the summary, do not recap what was happening, '
            'do not preface with "I\'ll continue" or similar. Pick up the '
            'last task as if the break never happened.'
        )

    return base


# ---------------------------------------------------------------------------
# Compaction result
# ---------------------------------------------------------------------------

@dataclass
class CompactionResult:
    """Outcome of a ``compact_conversation`` call."""

    boundary_message: AgentMessage
    summary_messages: list[AgentMessage] = field(default_factory=list)
    messages_to_keep: list[AgentMessage] = field(default_factory=list)
    pre_compact_token_count: int = 0
    post_compact_token_count: int = 0
    summary_text: str = ''
    usage: UsageStats = field(default_factory=UsageStats)
    error: str | None = None


# ---------------------------------------------------------------------------
# Core compaction logic
# ---------------------------------------------------------------------------

def compact_conversation(
    agent: 'LocalCodingAgent',
    custom_instructions: str | None = None,
) -> CompactionResult:
    """Perform an LLM-backed conversation compaction.

    1. Build the compact prompt (9-section template).
    2. Collect the session messages to summarise.
    3. Send them + the compact prompt to the model.
    4. Parse ``<summary>`` from the response.
    5. Replace session messages with:
       boundary marker → summary user message → preserved tail.

    Returns a :class:`CompactionResult` with diagnostics.
    """
    session = agent.last_session
    if session is None or len(session.messages) == 0:
        return CompactionResult(
            boundary_message=_build_boundary('No session to compact.'),
            error=ERROR_NOT_ENOUGH_MESSAGES,
        )

    # ---- Determine which messages to compact vs preserve ----
    # We keep the most recent ``preserve_count`` messages untouched.
    preserve_count = max(
        getattr(agent.runtime_config, 'compact_preserve_messages', 4), 1
    )

    # Identify the prefix count (system-injected messages that precede the
    # real conversation, e.g. a compaction-replay boundary).
    prefix_count = 0
    for msg in session.messages:
        if msg.metadata.get('kind') == 'compact_boundary':
            prefix_count += 1
        else:
            break

    total = len(session.messages)
    tail_count = min(preserve_count, max(total - prefix_count, 0))
    compact_end = total - tail_count

    # 2026-04-27: orphan-tool_result fix (re-applied after refactor reverted).
    # Walk compact_end forward past any leading tool_result messages so the
    # preserved tail never starts with an orphan. Handles 3 shapes:
    # role='tool', role='user' + tool_call_id, role='user' + content[*].type='tool_result'.
    def _msg_is_tool_result(m) -> bool:
        if m.role == 'tool':
            return True
        if m.role == 'user' and m.tool_call_id is not None:
            return True
        if m.role == 'user' and m.blocks:
            for block in m.blocks:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    return True
        return False

    while compact_end < total and _msg_is_tool_result(session.messages[compact_end]):
        compact_end += 1

    if compact_end <= prefix_count:
        return CompactionResult(
            boundary_message=_build_boundary('Not enough messages after prefix.'),
            error=ERROR_NOT_ENOUGH_MESSAGES,
        )

    candidates = session.messages[prefix_count:compact_end]
    preserved_tail = list(session.messages[compact_end:])

    if not candidates:
        return CompactionResult(
            boundary_message=_build_boundary('Nothing to compact.'),
            error=ERROR_NOT_ENOUGH_MESSAGES,
        )

    # ---- Estimate pre-compact token count ----
    model = agent.model_config.model
    pre_tokens = sum(estimate_tokens(m.content, model) for m in session.messages)

    # ---- Build the compact request messages ----
    compact_prompt = get_compact_prompt(custom_instructions)

    # We send the system prompt + candidate messages + the compact prompt as
    # a user message.  The model returns the summary.
    api_messages: list[dict[str, Any]] = []

    # System prompt (from session)
    for part in session.system_prompt_parts:
        if part.strip():
            api_messages.append({'role': 'system', 'content': part})

    # Candidate messages (the ones to be summarised)
    for msg in candidates:
        api_messages.append(msg.to_openai_message())

    # The compact prompt as the final user turn
    api_messages.append({'role': 'user', 'content': compact_prompt})

    # ---- Call the model ----
    try:
        turn = agent.client.complete(api_messages, tools=[])
    except Exception as exc:
        return CompactionResult(
            boundary_message=_build_boundary(f'Compact API call failed: {exc}'),
            error=str(exc),
        )

    raw_summary = turn.content or ''
    if not raw_summary.strip():
        return CompactionResult(
            boundary_message=_build_boundary('Model returned empty summary.'),
            error=ERROR_INCOMPLETE_RESPONSE,
        )

    # ---- Format the summary ----
    summary_text = format_compact_summary(raw_summary)
    user_summary_content = get_compact_user_summary_message(raw_summary)

    # ---- Build post-compact messages ----
    boundary = _build_boundary(
        f'Earlier conversation ({len(candidates)} messages, ~{pre_tokens} tokens) '
        f'was compacted.',
    )

    summary_msg = AgentMessage(
        role='user',
        content=user_summary_content,
        message_id='compact_summary',
        metadata={'kind': 'compact_summary', 'is_compact_summary': True},
    )

    # Replace session messages in-place
    session.messages = (
        session.messages[:prefix_count]
        + [boundary, summary_msg]
        + preserved_tail
    )

    # ---- Post-compact token estimate ----
    post_tokens = sum(estimate_tokens(m.content, model) for m in session.messages)

    return CompactionResult(
        boundary_message=boundary,
        summary_messages=[summary_msg],
        messages_to_keep=preserved_tail,
        pre_compact_token_count=pre_tokens,
        post_compact_token_count=post_tokens,
        summary_text=summary_text,
        usage=turn.usage,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_boundary(note: str) -> AgentMessage:
    """Create a compact-boundary system message."""
    return AgentMessage(
        role='user',
        content=f'<system-reminder>\n{note}\n</system-reminder>',
        message_id='compact_boundary',
        metadata={'kind': 'compact_boundary'},
    )
