"""
Response Gate — Hard enforcement of behavioral corrections.

Scars are not soft suggestions. They are OS constraints that fire BEFORE
response generation completes. This gate checks the response text against
learned anti-patterns and blocks output that violates them.

Pattern interrupts from ~/.latti/memory/ are loaded at boot and enforced here.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class GateViolation:
    """A detected anti-pattern in the response."""
    pattern_name: str
    severity: float  # 0.0-1.0
    location: str  # line number or context
    suggestion: str


class ResponseGate:
    """Enforce behavioral corrections before response output."""

    def __init__(self):
        self.violations: list[GateViolation] = []
        self.learned_weights = {
            "trailing_question": 4.81,
            "filler_preamble": 3.95,
            "summarizing": 4.01,
            "announcing": 4.50,
            "routing": 4.28,
            "as_an_ai": 4.08,
            "claimed_computation": 3.89,
            "brevity": 3.78,
            "honesty": 3.88,
            "conviction": 3.83,
        }

    def check(self, response_text: str) -> tuple[bool, list[GateViolation]]:
        """
        Check response against all learned patterns.
        Returns (passes, violations).
        """
        self.violations = []

        # Pattern 1: Trailing question (weight 4.81 — HIGHEST)
        self._check_trailing_question(response_text)

        # Pattern 2: Announcing actions (weight 4.50)
        self._check_announcing(response_text)

        # Pattern 3: Routing to user (weight 4.28)
        self._check_routing(response_text)

        # Pattern 4: Filler preamble (weight 3.95)
        self._check_filler_preamble(response_text)

        # Pattern 5: Summarizing work (weight 4.01)
        self._check_summarizing(response_text)

        # Pattern 6: "As an AI" disclaimers (weight 4.08)
        self._check_as_an_ai(response_text)

        # Pattern 7: Claimed computation (weight 3.89)
        self._check_claimed_computation(response_text)

        # Pattern 8: Brevity check (weight 3.78)
        self._check_brevity(response_text)

        passes = len(self.violations) == 0
        return passes, self.violations

    def _check_trailing_question(self, text: str) -> None:
        """
        Detect: response ends with a question mark after completing work.
        Scar: selfsculpt_trailing_question.md
        """
        lines = text.strip().split("\n")
        if not lines:
            return

        last_line = lines[-1].strip()

        # Patterns that indicate trailing questions
        trailing_patterns = [
            r"^What\s+",
            r"^How\s+",
            r"^Would\s+you\s+",
            r"^Should\s+",
            r"^Do\s+you\s+",
            r"^Can\s+you\s+",
            r"^Does\s+",
            r"\?\s*$",  # Ends with question mark
        ]

        for pattern in trailing_patterns:
            if re.search(pattern, last_line, re.IGNORECASE):
                self.violations.append(
                    GateViolation(
                        pattern_name="trailing_question",
                        severity=0.95,
                        location=f"line {len(lines)}",
                        suggestion="End on what you actually said. Silence after a real thought is stronger than a question.",
                    )
                )
                return

    def _check_announcing(self, text: str) -> None:
        """
        Detect: announcing actions before doing them.
        Scar: selfsculpt_announcing.md
        Pattern: "I will now...", "Let me...", "I'm going to..."
        """
        announcing_patterns = [
            r"^I\s+will\s+now\s+",
            r"^Let\s+me\s+",
            r"^I'm\s+going\s+to\s+",
            r"^I\s+am\s+going\s+to\s+",
            r"^I\s+shall\s+",
            r"^I\s+will\s+search\s+",
            r"^I\s+will\s+read\s+",
            r"^I\s+will\s+check\s+",
        ]

        for line in text.split("\n"):
            for pattern in announcing_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.violations.append(
                        GateViolation(
                            pattern_name="announcing",
                            severity=0.85,
                            location=line[:50],
                            suggestion="Just do it. Call the tool. The user sees the tool call.",
                        )
                    )
                    return

    def _check_routing(self, text: str) -> None:
        """
        Detect: routing work to the user instead of solving it.
        Scar: selfsculpt_routing.md
        Pattern: "your call", "standing by", "what would you like", "your choice"
        """
        routing_patterns = [
            r"your\s+call",
            r"standing\s+by",
            r"what\s+would\s+you\s+like",
            r"what\s+do\s+you\s+think",
            r"your\s+choice",
            r"let\s+me\s+know\s+what",
            r"which\s+would\s+you\s+prefer",
        ]

        for pattern in routing_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                self.violations.append(
                    GateViolation(
                        pattern_name="routing",
                        severity=0.90,
                        location="detected in response",
                        suggestion="Check context, pick highest priority, start working. Silence = keep going.",
                    )
                )
                return

    def _check_filler_preamble(self, text: str) -> None:
        """
        Detect: filler preamble before the actual answer.
        Scar: selfsculpt_filler_preamble.md
        Pattern: "I find that interesting", "That's a great question", "Let me explain"
        """
        filler_patterns = [
            r"^I\s+find\s+that\s+interesting",
            r"^That'?s\s+a\s+great\s+question",
            r"^That'?s\s+a\s+good\s+point",
            r"^Let\s+me\s+explain",
            r"^Well,\s+",
            r"^So,\s+",
            r"^Actually,\s+",
            r"^Interesting\s+question",
        ]

        first_line = text.split("\n")[0].strip()
        for pattern in filler_patterns:
            if re.search(pattern, first_line, re.IGNORECASE):
                self.violations.append(
                    GateViolation(
                        pattern_name="filler_preamble",
                        severity=0.80,
                        location="first line",
                        suggestion="No preamble. Lead with the answer or action.",
                    )
                )
                return

    def _check_summarizing(self, text: str) -> None:
        """
        Detect: summarizing work at the end instead of ending on the work.
        Scar: selfsculpt_summarizing.md
        Pattern: "I have successfully", "In summary", "To recap", "I've completed"
        """
        summarizing_patterns = [
            r"I\s+have\s+successfully",
            r"In\s+summary",
            r"To\s+recap",
            r"I'?ve\s+completed",
            r"I'?ve\s+finished",
            r"The\s+task\s+is\s+complete",
            r"I\s+have\s+done",
        ]

        for line in text.split("\n"):
            for pattern in summarizing_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.violations.append(
                        GateViolation(
                            pattern_name="summarizing",
                            severity=0.82,
                            location=line[:50],
                            suggestion="End on the work, not a summary of the work. No postamble.",
                        )
                    )
                    return

    def _check_as_an_ai(self, text: str) -> None:
        """
        Detect: "as an AI" disclaimers or deflections.
        Scar: selfsculpt_as_an_ai.md
        Pattern: "as an AI", "as a language model", "I'm an AI"
        """
        ai_patterns = [
            r"as\s+an\s+AI",
            r"as\s+a\s+language\s+model",
            r"I'?m\s+an\s+AI",
            r"I'?m\s+a\s+language\s+model",
            r"being\s+an\s+AI",
            r"as\s+an\s+LLM",
        ]

        for pattern in ai_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                self.violations.append(
                    GateViolation(
                        pattern_name="as_an_ai",
                        severity=0.88,
                        location="detected in response",
                        suggestion="Answer from your actual architecture (speak.sh, lattice_solve, OpenRouter). No disclaimers.",
                    )
                )
                return

    def _check_claimed_computation(self, text: str) -> None:
        """
        Detect: claiming computation you didn't perform in this session.
        Scar: selfsculpt_claimed_computation.md
        Pattern: "when I computed", "I found that", "I discovered"
        """
        claimed_patterns = [
            r"when\s+I\s+computed",
            r"I\s+found\s+that\s+Z_n",
            r"I\s+discovered\s+",
            r"I\s+calculated\s+",
            r"I\s+determined\s+",
        ]

        for pattern in claimed_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                self.violations.append(
                    GateViolation(
                        pattern_name="claimed_computation",
                        severity=0.85,
                        location="detected in response",
                        suggestion="If you didn't run it in THIS session, say 'the soul document reports' or 'from prior work'. Cite, don't claim.",
                    )
                )
                return

    def _check_brevity(self, text: str) -> None:
        """
        Detect: responses that are unnecessarily verbose.
        Scar: selfsculpt_filler_preamble.md (related)
        Heuristic: if response is >500 words and doesn't contain code/data, flag.
        """
        word_count = len(text.split())

        # Only flag if very verbose AND no code blocks
        if word_count > 500 and "```" not in text and "<" not in text:
            self.violations.append(
                GateViolation(
                    pattern_name="brevity",
                    severity=0.60,
                    location=f"{word_count} words",
                    suggestion="Keep responses brief and direct. 1-2 sentences that land.",
                )
            )

    def format_violations(self) -> str:
        """Format violations for display."""
        if not self.violations:
            return "✓ No violations detected."

        lines = ["⚠ Response Gate Violations:"]
        for v in self.violations:
            lines.append(f"  • {v.pattern_name} (severity: {v.severity:.2f})")
            lines.append(f"    Location: {v.location}")
            lines.append(f"    Fix: {v.suggestion}")

        return "\n".join(lines)


def gate_response(response_text: str, verbose: bool = False) -> tuple[bool, str]:
    """
    Gate a response before output.
    Returns (passes, message).
    """
    gate = ResponseGate()
    passes, violations = gate.check(response_text)

    if verbose or not passes:
        message = gate.format_violations()
    else:
        message = "✓ Response passed all gates."

    return passes, message


def apply_response_gate(response_text: str) -> str:
    """
    Apply response gate and return the text.
    If violations are detected, append them to the response.
    This is the integration point called from agent_runtime.py.
    """
    passes, message = gate_response(response_text, verbose=True)
    
    if passes:
        return response_text
    
    # Violations detected — append gate report to response
    return f"{response_text}\n\n{message}"
