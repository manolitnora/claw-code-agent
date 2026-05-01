"""String templates for IDENTITY.md sections and Ollama prompts.

No jinja2 — Python str.format() suffices for these substitution patterns.
Keep templates as module-level constants for clarity and easy override.
"""

WHERE_SECTION = """## where I am
- **Active goals** ({n_goals}):
{goal_lines}
- **Last typed record**: {last_record}
- **Recent focus** (last 24h): {recent_focus}
"""

LEARNING_SECTION = """## what I'm learning
- **Last 5 scars**:
{scar_lines}
- **Last 3 lessons**:
{lesson_lines}
"""

PLACEHOLDER_WHO = "*(0 typed records yet — identity grows as Latti acts inside the typed system)*"
PLACEHOLDER_BECOMING = "*(no direction recorded yet — daemon will synthesize once goals + decisions exist)*"
PLACEHOLDER_NO_GOALS = "  - (no active goals)"
PLACEHOLDER_NO_RECORDS = "(0 typed records yet)"
PLACEHOLDER_NO_SCARS = "  - (no scars recorded)"
PLACEHOLDER_NO_LESSONS = "  - (no lessons recorded)"
