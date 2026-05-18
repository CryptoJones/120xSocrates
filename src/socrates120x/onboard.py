"""The `socrates onboard` subcommand — synthesize a 60-second WELCOME.md.

No interview, no LLM. Pure file-reading + reformatting. The point is to give
a new collaborator (human or agent) the load-bearing facts in one minute,
without making them read 7 files.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

MAX_BULLETS = 3


def synthesize_welcome(project: Path) -> str:
    """Read the planning files at *project* and return a WELCOME.md body."""
    today = _dt.date.today().isoformat()
    name = project.name

    readme = (project / "README.md").read_text(errors="replace") if (project / "README.md").is_file() else ""
    agents = (project / "AGENTS.md").read_text(errors="replace") if (project / "AGENTS.md").is_file() else ""
    state = (project / "planning" / "STATE.md").read_text(errors="replace") if (project / "planning" / "STATE.md").is_file() else ""
    decisions = (project / "planning" / "DECISIONS.md").read_text(errors="replace") if (project / "planning" / "DECISIONS.md").is_file() else ""
    risks = (project / "planning" / "RISKS.md").read_text(errors="replace") if (project / "planning" / "RISKS.md").is_file() else ""
    questions = (project / "planning" / "QUESTIONS.md").read_text(errors="replace") if (project / "planning" / "QUESTIONS.md").is_file() else ""

    tagline = _extract_tagline(readme, agents)
    client = _extract_field(agents, "Client") or _extract_field(readme, "Client")
    tech = _extract_field(agents, "Tech stack")

    current_sprint = _extract_section_paragraph(state, "Active sprint") or "_(no active sprint listed)_"
    status = _extract_section_paragraph(state, "Status") or "_(no current status)_"
    next_action = _extract_section_paragraph(state, "Next action") or "_(no next action)_"

    top_decisions = _top_bullets(decisions, "Decisions captured", MAX_BULLETS)
    out_of_scope = _top_bullets(decisions, "Explicitly out of scope", MAX_BULLETS)
    top_risks = _top_bullets(risks, "Risks", MAX_BULLETS)
    top_questions = _top_bullets(questions, "Open", MAX_BULLETS)

    active_sprint_path = _active_sprint_path(project)

    return f"""# WELCOME — {name}

_60-second briefing. Generated {today} by `socrates onboard`._

**What it is:** {tagline or "_(no tagline)_"}
{f"**Client:** {client}  " if client else ""}{f"**Tech stack:** {tech}" if tech else ""}

## Right now

{current_sprint}

**Status:** {status}

**Next action:** {next_action}

## Load-bearing decisions

{_bullets_or(top_decisions, "_(none recorded yet — see planning/DECISIONS.md)_")}

## What is explicitly OUT of scope

{_bullets_or(out_of_scope, "_(no out-of-scope items listed)_")}

## Live risks

{_bullets_or(top_risks, "_(no risks recorded — see planning/RISKS.md)_")}

## Open questions

{_bullets_or(top_questions, "_(no open questions — see planning/QUESTIONS.md)_")}

## Where to start work

{_start_pointer(active_sprint_path)}

## Going deeper

- `AGENTS.md` — full project router (read second, after this file).
- `planning/STATE.md` — current sprint snapshot.
- `planning/DECISIONS.md`, `planning/DOMAIN.md`, `planning/RISKS.md`, `planning/QUESTIONS.md` — full versions of the lists above.
- `planning/sprints/` — every sprint's requirements / blueprint / acceptance.
- `planning/journal/` — append-only daily entries.

_This file is auto-generated. Do not hand-edit; re-run `socrates onboard` after planning changes._
"""


def write_welcome(project: Path) -> Path:
    """Write WELCOME.md into the project root and return its path."""
    body = synthesize_welcome(project)
    target = project / "WELCOME.md"
    target.write_text(body)
    return target


# ---------------------------------------------------------------------------
# Parsing helpers (deliberately small — these are not robust markdown parsers)
# ---------------------------------------------------------------------------


def _extract_tagline(readme: str, agents: str) -> str:
    # README first line that is not the H1 title.
    for line in readme.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!") or line.startswith("["):
            continue  # badge / image line
        return line
    # Fall back to AGENTS.md "What this project is" — the line after **NAME** — TEXT
    m = re.search(r"\*\*[^*]+\*\*\s+—\s+(.+)", agents)
    if m:
        return m.group(1).strip()
    return ""


def _extract_field(text: str, label: str) -> str:
    """Find a line like `**Label:** value` or `Label: value` and return the value."""
    pattern = re.compile(rf"\*?\*?{re.escape(label)}\*?\*?\s*:\s*\*?\*?([^*\n]+)\*?\*?", re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return ""
    return m.group(1).strip()


def _extract_section_paragraph(text: str, heading: str) -> str:
    """Pull the body of `## Heading` until the next heading."""
    lines = text.splitlines()
    capturing = False
    body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if capturing:
                break
            if heading.lower() in line.lower():
                capturing = True
                continue
        elif capturing:
            body.append(line)
    return "\n".join(body).strip()


def _top_bullets(text: str, heading_substr: str, n: int) -> list[str]:
    """Return the first n top-level `- ` bullets under a heading that matches heading_substr."""
    lines = text.splitlines()
    capturing = False
    items: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if capturing:
                break
            if heading_substr.lower() in line.lower():
                capturing = True
                continue
        elif capturing:
            stripped = line.lstrip()
            if stripped.startswith("- ") and not stripped.startswith("- _"):
                item = stripped[2:].strip().strip("*").strip()
                if item:
                    items.append(item)
                    if len(items) >= n:
                        break
    return items


def _bullets_or(items: list[str], fallback: str) -> str:
    if not items:
        return fallback
    return "\n".join(f"- {item}" for item in items)


def _active_sprint_path(project: Path) -> Path | None:
    sprints = project / "planning" / "sprints"
    if not sprints.is_dir():
        return None
    candidates = sorted(p for p in sprints.iterdir() if p.is_dir())
    # Heuristic: the highest-numbered sprint folder.
    if not candidates:
        return None
    return candidates[-1]


def _start_pointer(sprint: Path | None) -> str:
    if sprint is None:
        return "_(no sprint folders found — run `socrates init` first or check planning/sprints/)_"
    return (
        f"1. Read `{sprint.relative_to(sprint.parent.parent.parent)}/requirements.md`.\n"
        f"2. Read the matching `blueprint.md` and `acceptance.md`.\n"
        f"3. Confirm scope back to the operator before writing code."
    )
