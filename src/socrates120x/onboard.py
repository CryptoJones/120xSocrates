"""The `socrates onboard` subcommand — synthesize a 60-second WELCOME.md.

No interview, no LLM. Pure file-reading + reformatting. The point is to give
a new collaborator (human or agent) the load-bearing facts in one minute,
without making them read 7 files.

Source selection:

1. If `.socrates-answers.json` exists in the project, use it as the primary
   source — it is structured and not subject to markdown-parse drift.
2. Otherwise, fall back to regex parsing of the rendered planning files.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any

MAX_BULLETS = 3


def synthesize_welcome(project: Path) -> str:
    """Read the planning files at *project* and return a WELCOME.md body."""
    answers = _load_answers_json(project)
    if answers is not None:
        return _synthesize_from_answers(project, answers)
    return _synthesize_from_markdown(project)


def _load_answers_json(project: Path) -> dict[str, Any] | None:
    path = project / ".socrates-answers.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return None


def _synthesize_from_answers(project: Path, answers: dict[str, Any]) -> str:
    """Build WELCOME.md directly from the structured answer dict."""
    today = _dt.date.today().isoformat()
    name = answers.get("project_name") or project.name
    tagline = answers.get("tagline") or ""
    client = answers.get("client") or ""
    tech = answers.get("tech_stack") or ""
    status = answers.get("state_current") or "_(no current status)_"
    next_action = answers.get("state_next") or "_(no next action)_"

    decisions_list = answers.get("decisions") or []
    # `answers.decisions` is frozen at init time — it does NOT include
    # post-init decisions appended by `socrates decide`. Read those from
    # DECISIONS.md's "Decisions added after init" section and prepend so
    # the freshest decisions appear first in WELCOME.md.
    post_init = _post_init_decisions(project)
    combined_decisions = [*post_init, *[str(d) for d in decisions_list]]

    out_of_scope = answers.get("out_of_scope") or []
    risks_list = answers.get("risks") or []
    open_questions = answers.get("open_questions") or []

    top_decisions = combined_decisions[:MAX_BULLETS]
    top_out_of_scope = [str(o) for o in out_of_scope[:MAX_BULLETS]]
    top_risks = [str(r) for r in risks_list[:MAX_BULLETS]]
    top_questions = [str(q) for q in open_questions[:MAX_BULLETS]]

    # Pick the highest-numbered sprint directory rather than hardcoding "001".
    # A project on sprint 005 should not have its WELCOME.md still announce
    # "001 — Discovery & Architecture" just because answers.json was the
    # original init record.
    active_sprint_path = _active_sprint_path(project)
    current_sprint = _format_sprint_label(active_sprint_path)
    return _format_welcome(
        name=name, today=today, tagline=tagline, client=client, tech=tech,
        current_sprint=current_sprint, status=status, next_action=next_action,
        top_decisions=top_decisions, out_of_scope=top_out_of_scope,
        top_risks=top_risks, top_questions=top_questions,
        active_sprint_path=active_sprint_path,
    )


def _synthesize_from_markdown(project: Path) -> str:
    """Fallback: parse the rendered markdown files (used when no answers.json)."""
    today = _dt.date.today().isoformat()
    name = project.name

    readme = (project / "README.md").read_text(errors="replace", encoding="utf-8") if (project / "README.md").is_file() else ""
    agents = (project / "AGENTS.md").read_text(errors="replace", encoding="utf-8") if (project / "AGENTS.md").is_file() else ""
    state = (project / "planning" / "STATE.md").read_text(errors="replace", encoding="utf-8") if (project / "planning" / "STATE.md").is_file() else ""
    decisions = (project / "planning" / "DECISIONS.md").read_text(errors="replace", encoding="utf-8") if (project / "planning" / "DECISIONS.md").is_file() else ""
    risks = (project / "planning" / "RISKS.md").read_text(errors="replace", encoding="utf-8") if (project / "planning" / "RISKS.md").is_file() else ""
    questions = (project / "planning" / "QUESTIONS.md").read_text(errors="replace", encoding="utf-8") if (project / "planning" / "QUESTIONS.md").is_file() else ""

    tagline = _extract_tagline(readme, agents)
    client = _extract_field(agents, "Client") or _extract_field(readme, "Client")
    tech = _extract_field(agents, "Tech stack")

    # Prefer the sprint directory listing (ground truth) over whatever
    # STATE.md happens to say, which drifts over time. Fall back to STATE.md
    # only if no canonical NNN- sprint folders exist.
    active_sprint_for_label = _active_sprint_path(project)
    if active_sprint_for_label is not None:
        current_sprint = _format_sprint_label(active_sprint_for_label)
    else:
        current_sprint = _extract_section_paragraph(state, "Active sprint") or "_(no active sprint listed)_"
    status = _extract_section_paragraph(state, "Status") or "_(no current status)_"
    next_action = _extract_section_paragraph(state, "Next action") or "_(no next action)_"

    # Combine init + post-init decisions. The markdown DECISIONS.md may have
    # two sections: 'Decisions captured during Sprint 001 discovery' (init)
    # AND 'Decisions added after init' (from `socrates decide`). Show the
    # freshest first.
    post_init_decisions = _top_bullets(decisions, "Decisions added after init", MAX_BULLETS)
    init_decisions = _top_bullets(decisions, "Decisions captured", MAX_BULLETS)
    top_decisions = [*post_init_decisions, *init_decisions][:MAX_BULLETS]
    out_of_scope = _top_bullets(decisions, "Explicitly out of scope", MAX_BULLETS)
    top_risks = _top_bullets(risks, "Risks", MAX_BULLETS)
    top_questions = _top_bullets(questions, "Open", MAX_BULLETS)

    active_sprint_path = _active_sprint_path(project)
    return _format_welcome(
        name=name, today=today, tagline=tagline, client=client, tech=tech,
        current_sprint=current_sprint, status=status, next_action=next_action,
        top_decisions=top_decisions, out_of_scope=out_of_scope,
        top_risks=top_risks, top_questions=top_questions,
        active_sprint_path=active_sprint_path,
    )


def _format_welcome(
    *,
    name: str,
    today: str,
    tagline: str,
    client: str,
    tech: str,
    current_sprint: str,
    status: str,
    next_action: str,
    top_decisions: list[str],
    out_of_scope: list[str],
    top_risks: list[str],
    top_questions: list[str],
    active_sprint_path: Path | None,
) -> str:

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
    target.write_text(body, encoding="utf-8")
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


_POST_INIT_BULLET = re.compile(r"^-\s*\*?\*?(.+?)\*?\*?\s*$")


def _post_init_decisions(project: Path, limit: int = MAX_BULLETS) -> list[str]:
    """Read DECISIONS.md and return up to *limit* bullets from the
    'Decisions added after init' section, most recent first.

    `_synthesize_from_answers` otherwise misses every decision the
    operator added via `socrates decide` after the initial interview.
    """
    decisions_path = project / "planning" / "DECISIONS.md"
    if not decisions_path.is_file():
        return []
    text = decisions_path.read_text(encoding="utf-8", errors="replace")
    capturing = False
    items: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if capturing:
                break
            if "decisions added after init" in line.lower():
                capturing = True
            continue
        if not capturing:
            continue
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        m = _POST_INIT_BULLET.match(stripped)
        if not m:
            continue
        body = m.group(1).strip()
        if body:
            items.append(body)
    # Newest decisions live at the BOTTOM of the section (record_decision
    # appends). Reverse so WELCOME.md shows the most recent first.
    items.reverse()
    return items[:limit]


def _active_sprint_path(project: Path) -> Path | None:
    sprints = project / "planning" / "sprints"
    if not sprints.is_dir():
        return None
    # Only count folders whose name matches the canonical `NNN-...` pattern;
    # ignore stray dirs (drafts, backups). Highest number wins.
    canonical = re.compile(r"^(\d{3})-")
    numbered = [
        (int(m.group(1)), p)
        for p in sprints.iterdir()
        if p.is_dir() and (m := canonical.match(p.name))
    ]
    if not numbered:
        return None
    numbered.sort()
    return numbered[-1][1]


def _format_sprint_label(sprint: Path | None) -> str:
    """Turn `planning/sprints/005-rebate-engine` into
    `**005 — Rebate Engine**` for the WELCOME.md header.
    Returns a placeholder if no sprint folder exists."""
    if sprint is None:
        return "_(no sprint folders found — run `socrates init` first or add planning/sprints/NNN-…)_"
    name = sprint.name  # e.g. "005-rebate-engine" or "001-discovery-architecture"
    m = re.match(r"^(\d{3})-(.+)$", name)
    if not m:
        return f"**{name}**"
    number = m.group(1)
    slug = m.group(2)
    # Convert kebab-case → Title Case for the human label.
    pretty = " ".join(part.capitalize() for part in slug.split("-"))
    return f"**{number} — {pretty}**"


def _start_pointer(sprint: Path | None) -> str:
    if sprint is None:
        return "_(no sprint folders found — run `socrates init` first or check planning/sprints/)_"
    return (
        f"1. Read `{sprint.relative_to(sprint.parent.parent.parent)}/requirements.md`.\n"
        f"2. Read the matching `blueprint.md` and `acceptance.md`.\n"
        f"3. Confirm scope back to the operator before writing code."
    )
