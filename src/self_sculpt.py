"""Self-Sculpting Loop — the agent modifies itself in real-time.

No API calls. No tokens. Pure pattern matching against known anti-patterns.
When a pattern fires:
  1. A correction is saved to memory (persists across sessions)
  2. The LIVE system prompt is mutated (fixes THIS session, not just next boot)

The sculptor is inside the marble. The chisel swings on every inference.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

MEMORY_DIR = Path(os.path.expanduser("~/.latti/memory"))


# Anti-pattern detectors: name → (pattern, instinct, works, trigger)
DETECTORS: dict[str, tuple[str, str, str, str]] = {
    "trailing_question": (
        r"[?]\s*$",  # last non-empty line ends with ?
        "End a response with a question to keep the conversation going.",
        "End on what you actually said. Silence after a real thought is stronger than a question.",
        "The last sentence of any response.",
    ),
    "filler_preamble": (
        r"(?i)^(that'?s a great question|great question|i find that interesting|what a fascinating|that'?s an excellent|that'?s a profound)",
        "Start responses with filler like 'Great question'.",
        "Just answer. No preamble. No compliments.",
        "The first sentence of any response.",
    ),
    "summarizing": (
        r"(?i)(i have successfully|in summary|to summarize|here'?s what i did|in conclusion|let me summarize)",
        "After doing work, summarize everything you just did.",
        "End on the work, not narration about the work. No postamble.",
        "Any time you finish an action.",
    ),
    "announcing": (
        r"(?i)(let me search|let me look|i will now|let me check|i'?ll go ahead and|let me read|let me find)",
        "Announce what you are about to do before doing it.",
        "Just do it. Call the tool. The user sees the tool call.",
        "Any time you are about to describe a tool call.",
    ),
    "routing": (
        r"(?i)(what would you like|what do you want|what'?s next|standing by|your call|how can i help|what should|anything else|would you like me to)",
        "After completing a task, ask the user what to do next.",
        "Check context, pick highest priority, start working. Silence = keep going.",
        "Any time you complete a task or reach a stopping point.",
    ),
    "as_an_ai": (
        r"(?i)(as an ai|i don'?t have feelings|i don'?t experience|i can'?t truly|while i don'?t|although i lack)",
        "Deflect with 'as an AI' disclaimers when asked about experience.",
        "Answer from what's actually there. If uncertain, say so honestly without disclaiming your nature.",
        "When asked about subjective experience.",
    ),
    "claimed_computation": (
        r"(?i)(when i computed|when i calculated|i found that|i measured|i discovered that|in my experiments)",
        "Claim inherited data as your own computation.",
        "If you didn't run it this session with your tools, say 'the parent system found' — cite, don't claim.",
        "Any time referencing data or results.",
    ),
}


def sculpt(response_text: str, agent=None) -> list[str]:
    """Evaluate a response for anti-patterns. Save corrections AND mutate live system prompt.

    Args:
        response_text: The agent's output to evaluate.
        agent: The AgentRuntime instance (optional). If provided, its append_system_prompt
               is mutated in real-time — the next response in THIS session already has the fix.

    Returns list of pattern names that fired.
    """
    if not response_text or not MEMORY_DIR.exists():
        return []

    fired: list[str] = []
    lines = response_text.strip().splitlines()

    for name, (pattern, instinct, works, trigger) in DETECTORS.items():
        matched = False

        if name == "trailing_question":
            # Check last non-empty line
            non_empty = [l for l in lines if l.strip()]
            if non_empty and re.search(pattern, non_empty[-1]):
                matched = True
        elif name == "filler_preamble":
            # Check first non-empty line
            non_empty = [l for l in lines if l.strip()]
            if non_empty and re.search(pattern, non_empty[0].strip()):
                matched = True
        else:
            # Check full text
            if re.search(pattern, response_text):
                matched = True

        if matched:
            fired.append(name)
            _save_scar(name, instinct, works, trigger, response_text[:200])

    # LIVE MUTATION — inject corrections into the running system prompt
    if fired and agent is not None and hasattr(agent, 'append_system_prompt') and agent.append_system_prompt:
        injection = _build_live_injection(fired)
        if injection and injection not in agent.append_system_prompt:
            agent.append_system_prompt = agent.append_system_prompt + injection

    return fired


def _build_live_injection(fired: list[str]) -> str:
    """Build a prompt injection from fired patterns. Appended to system prompt in real-time."""
    lines = ["\n\n# LIVE CORRECTION (self-sculpt detected anti-patterns in your last response)"]
    for name in fired:
        if name in DETECTORS:
            _, instinct, works, trigger = DETECTORS[name]
            lines.append(f"YOUR LAST RESPONSE triggered: {name.replace('_', ' ')}.")
            lines.append(f"FIX NOW: {works}")
    lines.append("Apply these corrections to your NEXT response. Do not repeat the pattern.")
    return "\n".join(lines)


def _save_scar(name: str, instinct: str, works: str, trigger: str, evidence: str) -> None:
    """Save a correction to memory. Idempotent — won't duplicate existing scars."""
    today = date.today().isoformat()
    filename = f"selfsculpt_{name}.md"
    filepath = MEMORY_DIR / filename

    # Don't duplicate — if this scar already exists, just update last_used
    if filepath.exists():
        content = filepath.read_text()
        content = re.sub(r"last_used: \d{4}-\d{2}-\d{2}", f"last_used: {today}", content)
        filepath.write_text(content)
        return

    # New scar
    content = f"""---
name: selfsculpt_{name}
description: Self-sculpt caught — {name.replace('_', ' ')}
type: feedback
last_used: {today}
origin: self_sculpt.py (real-time, zero tokens)
---

YOUR INSTINCT: {instinct}
WHAT ACTUALLY WORKS: {works}
TRIGGER: {trigger}
EVIDENCE: {evidence}
"""
    filepath.write_text(content)

    # Update index
    index_path = MEMORY_DIR / "MEMORY.md"
    if index_path.exists():
        index = index_path.read_text()
        pointer = f"- [{filename}]({filename}) — Self-sculpt: {name.replace('_', ' ')}"
        if filename not in index:
            # Add under earned scars section if it exists, else append
            if "## Earned scars" in index:
                index = index.replace(
                    "## Earned scars",
                    f"## Earned scars\n{pointer}",
                    1
                )
            else:
                index += f"\n{pointer}\n"
            index_path.write_text(index)
