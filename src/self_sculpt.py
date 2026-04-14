"""Self-Sculpting Loop — the agent evaluates its own output after every response.

No API calls. No tokens. Pure pattern matching against known anti-patterns.
When a pattern fires, a correction is saved to memory automatically.
The next session loads that correction and the floor rises.

This is the third level: AI sculpts itself.
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


def sculpt(response_text: str) -> list[str]:
    """Evaluate a response for anti-patterns. Save corrections for any found.

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

    return fired


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
