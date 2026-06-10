"""Derived documents — pure synthesis, no interview, no LLM.

`onboard` writes a 60-second WELCOME.md briefing for a new collaborator;
`pack` assembles the Architect input bundle (md / xml / html) for a
browser-chat session.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape as _xml_escape

# ─────────────────────────────────────────────────────────────────────────────
# onboard — synthesize a 60-second WELCOME.md from the planning files
# No interview, no LLM. Prefers .socrates-answers.json (structured); falls
# back to regex-parsing the rendered markdown.
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# pack — assemble the Architect input bundle
# Concatenates the load-bearing planning files + active sprint into one
# paste-able file for the Architect (browser chat). Formats: md (default),
# xml (markdown in <section> tags, ~5% token overhead, Anthropic-style
# delimitation), html (full conversion, ~30-50% overhead, needs the
# optional `markdown` package: pip install socrates120x[html]).
# ─────────────────────────────────────────────────────────────────────────────

# Files the kit-path option looks for, in order, in the kit directory.
KIT_FILES: tuple[str, ...] = (
    "120x-architect-builder-philosophy.md",
    "120x-project-scaffold-instructions.md",
    "120x-quickstart.md",
)

# A short, original Architect/Builder stance, prepended by --include-philosophy.
# Deliberately not copied from the 120x Operators Kit — use --kit-path if you
# want the kit's own files embedded in the pack.
ARCHITECT_PREAMBLE = """\
# 120x Architect / Builder stance (summary)

This project is run with two distinct AI roles, and you (the Architect) are
**one** of them. The other (the Builder) operates inside the project folder
on the operator's machine. The roles must stay separate:

- **You — the Architect.** You think, plan, and write *documents*. You ask
  the operator probing questions, surface assumptions, and produce planning
  artifacts (requirements, blueprints, acceptance criteria, handoff prompts).
  You **do not** write application code, you **do not** touch the filesystem,
  and you **do not** redefine scope without confirming with the operator.

- **The Builder.** A coding agent (Claude Code, Codex, Cursor, etc.) running
  in a terminal pointed at the project folder. It reads the planning files
  you produce and writes code that satisfies them. It does **not** invent
  business rules or pricing or product behaviour.

- **The handoff is a folder, not a conversation.** The source of truth is
  the project's `planning/` directory, not this chat thread. If something
  important comes up here, it must end up in `DECISIONS.md`, `RISKS.md`,
  `QUESTIONS.md`, or the active sprint folder. Otherwise it will not
  survive a new chat session or a new tool.

- **You never claim a sprint is done.** Done is determined by the sprint's
  `acceptance.md` criteria, evaluated by the Builder, confirmed by the
  operator. Your job is to ensure those criteria are objectively checkable
  before the Builder starts.

The rest of this bundle is the project's current planning state. Treat it
as the source of truth. If anything in it contradicts itself, say so and
ask — do not silently choose."""

PackFormat = Literal["md", "html", "xml"]
SUPPORTED_FORMATS: tuple[PackFormat, ...] = ("md", "html", "xml")


@dataclass(frozen=True)
class _Section:
    """One section of the pack — label, file source (if any), body, kind."""
    label: str
    body: str
    # `path` is the on-disk source for traceability; None for synthetic
    # sections (header, footer, philosophy preamble, sprint divider).
    path: str | None = None
    # Discriminator for the XML/HTML renderers so they can pick semantic
    # tags. The MD renderer doesn't use this.
    kind: str = "section"


def build_pack(
    project: Path,
    *,
    include_sprint: str | None = None,
    include_philosophy: bool = False,
    kit_path: Path | None = None,
    format: PackFormat = "md",
) -> str:
    """Return the full Architect input bundle as a single string.

    ``format`` selects the output language:
    - ``md`` (default): plain markdown
    - ``xml``: markdown wrapped in <section> tags
    - ``html``: full HTML (requires the optional `markdown` package)
    """
    if format not in SUPPORTED_FORMATS:
        raise ValueError(
            f"format must be one of {SUPPORTED_FORMATS!r}, got {format!r}"
        )

    sections = _collect_sections(
        project,
        include_sprint=include_sprint,
        include_philosophy=include_philosophy,
        kit_path=kit_path,
    )

    if format == "md":
        return _render_md(sections)
    if format == "xml":
        return _render_xml(project, sections)
    return _render_html(project, sections)


def write_pack(
    project: Path,
    *,
    include_sprint: str | None = None,
    include_philosophy: bool = False,
    kit_path: Path | None = None,
    format: PackFormat = "md",
) -> Path:
    body = build_pack(
        project,
        include_sprint=include_sprint,
        include_philosophy=include_philosophy,
        kit_path=kit_path,
        format=format,
    )
    target = project / f".socrates-architect-pack.{format}"
    target.write_text(body, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Section collection (format-independent)
# ---------------------------------------------------------------------------


def _collect_sections(
    project: Path,
    *,
    include_sprint: str | None,
    include_philosophy: bool,
    kit_path: Path | None,
) -> list[_Section]:
    out: list[_Section] = [_header_section(project)]

    if include_philosophy:
        out.append(_philosophy_section())

    resolved_kit = _resolve_kit_path(kit_path)
    if resolved_kit is not None:
        out.extend(_kit_sections(resolved_kit))

    for rel, label in (
        ("AGENTS.md", "Project router"),
        ("README.md", "Project README"),
        ("planning/STATE.md", "Current state"),
        ("planning/DOMAIN.md", "Client domain"),
        ("planning/DECISIONS.md", "Decisions"),
        ("planning/RISKS.md", "Risks"),
        ("planning/QUESTIONS.md", "Open questions"),
    ):
        out.append(_file_section(project / rel, rel_display=rel, label=label))

    sprint = _resolve_sprint(project, include_sprint)
    if sprint is not None:
        out.append(_Section(
            label=f"Active sprint: `{sprint.name}`",
            body="",
            kind="sprint-header",
        ))
        sprint_rel = sprint.relative_to(project).as_posix()
        for fname, label in (
            ("requirements.md", "Sprint requirements"),
            ("blueprint.md", "Sprint blueprint"),
            ("acceptance.md", "Sprint acceptance criteria"),
            ("handoff-prompt.md", "Sprint handoff prompt (Builder)"),
        ):
            out.append(_file_section(
                sprint / fname,
                rel_display=f"{sprint_rel}/{fname}",
                label=label,
            ))

    out.append(_footer_section())
    return out


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _header_section(project: Path) -> _Section:
    today = _dt.date.today().isoformat()
    body = f"""_Generated {today} by `socrates pack`. Paste this entire file into your Architect
session (Claude Chat / ChatGPT / etc.) as project context. The Architect should:_

1. _Read every section below in order._
2. _Update its understanding of the domain, decisions, and active sprint._
3. _Answer the operator's questions in a Builder-actionable form
   (planning artifacts, prompts, acceptance criteria — never code)._

_The Builder layer is downstream of this conversation; do not write source code here._"""
    return _Section(
        label=f"Architect input bundle — `{project.name}`",
        body=body,
        kind="header",
    )


def _footer_section() -> _Section:
    body = (
        "_End of bundle. The Architect should now ask the operator what they need next, "
        "treating everything above as the source of truth._"
    )
    return _Section(label="", body=body, kind="footer")


def _philosophy_section() -> _Section:
    """The ARCHITECT_PREAMBLE as a section.

    The preamble begins with its own top-level markdown header, so the
    renderers must avoid double-wrapping it.
    """
    return _Section(label="", body=ARCHITECT_PREAMBLE, kind="preamble-raw")


def _kit_sections(kit: Path) -> list[_Section]:
    out: list[_Section] = []
    for name in KIT_FILES:
        path = kit / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace", encoding="utf-8").strip()
        if not text:
            continue
        out.append(_Section(
            label=f"120x Operators Kit: `{name}`",
            body=text,
            path=name,
            kind="kit",
        ))
    return out


def _file_section(path: Path, *, rel_display: str, label: str) -> _Section:
    if not path.is_file():
        return _Section(
            label=f"{label}  (`{rel_display}`)",
            body="_(file not present — skipped)_",
            path=rel_display,
            kind="missing",
        )
    text = path.read_text(errors="replace", encoding="utf-8").strip()
    if not text:
        return _Section(
            label=f"{label}  (`{rel_display}`)",
            body="_(file is empty)_",
            path=rel_display,
            kind="empty",
        )
    return _Section(
        label=f"{label}  (`{rel_display}`)",
        body=text,
        path=rel_display,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_md(sections: list[_Section]) -> str:
    """Markdown renderer — the historical pack format."""
    parts: list[str] = []
    for s in sections:
        if s.kind == "footer":
            parts.append(f"---\n\n{s.body}")
            continue
        if s.kind == "preamble-raw":
            # Template already has its own top-level header; emit as-is.
            parts.append(s.body)
            continue
        if not s.label:
            parts.append(s.body)
            continue
        if s.body:
            parts.append(f"# {s.label}\n\n{s.body}")
        else:
            parts.append(f"# {s.label}\n")
    return "\n\n".join(filter(None, parts))


def _render_xml(project: Path, sections: list[_Section]) -> str:
    """XML renderer — markdown bodies wrapped in <section> tags.

    Matches Anthropic's published recommendation to use XML-style tags for
    structural delimitation when packing context for Claude. The section
    body remains markdown; only the delimiters are XML. ~5% token overhead.
    """
    today = _dt.date.today().isoformat()
    out: list[str] = [
        f'<bundle generated="{today}" project="{_xml_escape(project.name)}">'
    ]
    for s in sections:
        attrs = f' kind="{_xml_escape(s.kind)}"'
        if s.path:
            attrs += f' path="{_xml_escape(s.path)}"'
        if s.label:
            attrs += f' label="{_xml_escape(s.label)}"'
        # The body contains markdown — escape only the bare minimum so the
        # markdown stays readable. Standard XML chars `<`, `>`, `&` need
        # escaping; markdown's quote/apostrophe usage is irrelevant inside
        # element content.
        body = s.body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if s.kind == "footer":
            out.append(f"  <footer{attrs}>\n{body}\n  </footer>")
        elif s.kind == "header":
            out.append(f"  <header{attrs}>\n{body}\n  </header>")
        else:
            out.append(f"  <section{attrs}>\n{body}\n  </section>")
    out.append("</bundle>")
    return "\n".join(out)


def _render_html(project: Path, sections: list[_Section]) -> str:
    """HTML renderer — markdown converted via the optional `markdown` lib.

    Requires the ``markdown`` package. Install with
    ``pip install socrates120x[html]`` or ``pip install markdown``.

    Security: planning files can contain arbitrary content the operator
    pasted in (code samples, error logs, etc.). ``python-markdown`` passes
    raw HTML through verbatim — there is no built-in safe mode in v3+. A
    ``<script>`` snippet in any planning file would execute when the
    rendered bundle is opened in a browser for preview.

    The bundle is meant to be PASTED into an AI chat (which strips
    scripts) or PREVIEWED in a browser. It never needs JavaScript itself.
    So we ship a strict Content-Security-Policy meta tag:
      - ``script-src 'none'`` blocks both ``<script>`` tags and inline
        ``onclick=``/``onerror=`` handlers.
      - ``object-src 'none'`` blocks ``<object>`` / ``<embed>``.
      - ``frame-src 'none'`` blocks ``<iframe>`` (phishing redirect via
        a planted iframe).
      - ``base-uri 'none'`` blocks ``<base>`` tag rewriting that could
        redirect relative links.
      - ``style-src 'unsafe-inline'`` keeps inline styles (used by
        ``fenced_code`` syntax highlighting) but disables external CSS.
    """
    md = _import_markdown()
    today = _dt.date.today().isoformat()
    rendered_sections: list[str] = []
    for s in sections:
        body_html = md.markdown(
            s.body,
            extensions=["fenced_code", "tables"],
        ) if s.body else ""
        tag = "section"
        if s.kind == "header":
            tag = "header"
        elif s.kind == "footer":
            tag = "footer"
        attrs = f' data-kind="{_xml_escape(s.kind)}"'
        if s.path:
            attrs += f' data-path="{_xml_escape(s.path)}"'
        label_html = ""
        if s.label:
            label_html = f"  <h1>{_xml_escape(s.label)}</h1>\n"
        rendered_sections.append(
            f"<{tag}{attrs}>\n{label_html}  {body_html}\n</{tag}>"
        )
    body = "\n\n".join(rendered_sections)
    csp = (
        "default-src 'none'; "
        "script-src 'none'; "
        "object-src 'none'; "
        "frame-src 'none'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "style-src 'unsafe-inline'; "
        "img-src data:"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>Architect input bundle — {_xml_escape(project.name)}</title>
<meta name="generated" content="{today}">
<meta name="generator" content="socrates pack">
</head>
<body>
{body}
</body>
</html>"""


def _import_markdown() -> Any:
    try:
        import markdown  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised by error-path test
        raise RuntimeError(
            "--format html requires the `markdown` package. Install with "
            "`pip install socrates120x[html]` or `pip install markdown`."
        ) from exc
    return markdown


# ---------------------------------------------------------------------------
# Resolvers (kit, sprint)
# ---------------------------------------------------------------------------


def _resolve_kit_path(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve() if explicit.exists() else None
    env = os.environ.get("SOCRATES_KIT_PATH")
    if env:
        candidate = Path(env).expanduser().resolve()
        return candidate if candidate.is_dir() else None
    return None


def _resolve_sprint(project: Path, name: str | None) -> Path | None:
    sprints_dir = project / "planning" / "sprints"
    if not sprints_dir.is_dir():
        return None
    if name:
        candidate = sprints_dir / name
        return candidate if candidate.is_dir() else None
    candidates = sorted(p for p in sprints_dir.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None
