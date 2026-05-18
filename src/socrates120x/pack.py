"""The `socrates pack` subcommand — assemble an Architect input bundle.

Every command socrates ships helps the Builder side. The Architect side
(Claude Chat / ChatGPT in a browser) is unaided — operators paste planning
files by hand into a chat thread. `pack` produces the exact paste-able
bundle: one file containing every load-bearing planning document the
Architect needs, in a stable order, separated by clearly-labelled headers.

Output goes to `.socrates-architect-pack.md` in the project root by default,
or to stdout with `--stdout`.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path


def build_pack(project: Path, *, include_sprint: str | None = None) -> str:
    """Return the full Architect input bundle as a single markdown string.

    If ``include_sprint`` is given (e.g. "002-rebate-engine"), only that
    sprint folder's files are embedded; otherwise the active (highest-
    numbered) sprint is used.
    """
    sections: list[str] = []
    sections.append(_header(project))

    sections.append(_load("AGENTS.md", project, label="Project router"))
    sections.append(_load("README.md", project, label="Project README"))
    sections.append(_load("planning/STATE.md", project, label="Current state"))
    sections.append(_load("planning/DOMAIN.md", project, label="Client domain"))
    sections.append(_load("planning/DECISIONS.md", project, label="Decisions"))
    sections.append(_load("planning/RISKS.md", project, label="Risks"))
    sections.append(_load("planning/QUESTIONS.md", project, label="Open questions"))

    sprint = _resolve_sprint(project, include_sprint)
    if sprint is not None:
        sections.append(f"# Active sprint: `{sprint.name}`\n")
        for fname, label in (
            ("requirements.md", "Sprint requirements"),
            ("blueprint.md", "Sprint blueprint"),
            ("acceptance.md", "Sprint acceptance criteria"),
            ("handoff-prompt.md", "Sprint handoff prompt (Builder)"),
        ):
            sections.append(_load_rel(sprint / fname, label=label))

    sections.append(_footer())
    return "\n\n".join(filter(None, sections))


def write_pack(project: Path, *, include_sprint: str | None = None) -> Path:
    body = build_pack(project, include_sprint=include_sprint)
    target = project / ".socrates-architect-pack.md"
    target.write_text(body)
    return target


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _header(project: Path) -> str:
    today = _dt.date.today().isoformat()
    return f"""# Architect input bundle — `{project.name}`

_Generated {today} by `socrates pack`. Paste this entire file into your Architect
session (Claude Chat / ChatGPT / etc.) as project context. The Architect should:_

1. _Read every section below in order._
2. _Update its understanding of the domain, decisions, and active sprint._
3. _Answer the operator's questions in a Builder-actionable form
   (planning artifacts, prompts, acceptance criteria — never code)._

_The Builder layer is downstream of this conversation; do not write source code here._"""


def _footer() -> str:
    return (
        "---\n\n"
        "_End of bundle. The Architect should now ask the operator what they need next, "
        "treating everything above as the source of truth._"
    )


def _load(rel: str, project: Path, *, label: str) -> str:
    return _load_rel(project / rel, label=label)


def _load_rel(path: Path, *, label: str) -> str:
    rel_display = path.name if path.parent.name == "" else path.as_posix()
    if not path.is_file():
        return f"# {label}  (`{rel_display}`)\n\n_(file not present — skipped)_"
    text = path.read_text(errors="replace").strip()
    if not text:
        return f"# {label}  (`{rel_display}`)\n\n_(file is empty)_"
    return f"# {label}  (`{rel_display}`)\n\n{text}"


def _resolve_sprint(project: Path, name: str | None) -> Path | None:
    sprints_dir = project / "planning" / "sprints"
    if not sprints_dir.is_dir():
        return None
    if name:
        candidate = sprints_dir / name
        return candidate if candidate.is_dir() else None
    candidates = sorted(p for p in sprints_dir.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None
