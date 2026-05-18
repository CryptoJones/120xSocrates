"""The `socrates pack` subcommand — assemble an Architect input bundle.

Every command socrates ships helps the Builder side. The Architect side
(Claude Chat / ChatGPT in a browser) is unaided — operators paste planning
files by hand into a chat thread. `pack` produces the exact paste-able
bundle: one file containing every load-bearing planning document the
Architect needs, in a stable order, separated by clearly-labelled headers.

Output goes to `.socrates-architect-pack.md` in the project root by default,
or to stdout with `--stdout`.

Optional preambles:

- ``--include-philosophy`` embeds a short, original 120x stance written by
  socrates itself. Safe to include in every pack; never re-uploaded kit
  content. Useful when the Architect chat is fresh (no Project sources set
  up yet) and needs the Architect/Builder split explained inline.

- ``--kit-path PATH`` (or env var ``SOCRATES_KIT_PATH``) also embeds the
  three load-bearing files from a local 120x Operators Kit checkout
  (philosophy, scaffold-instructions, quickstart). Use this when you want
  the FULL kit context in the pack, not just socrates' short summary.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

# Files the kit-path option looks for, in order, in the kit directory.
KIT_FILES: tuple[str, ...] = (
    "120x-architect-builder-philosophy.md",
    "120x-project-scaffold-instructions.md",
    "120x-quickstart.md",
)


def build_pack(
    project: Path,
    *,
    include_sprint: str | None = None,
    include_philosophy: bool = False,
    kit_path: Path | None = None,
) -> str:
    """Return the full Architect input bundle as a single markdown string."""
    sections: list[str] = []
    sections.append(_header(project))

    if include_philosophy:
        sections.append(_philosophy_preamble())

    resolved_kit = _resolve_kit_path(kit_path)
    if resolved_kit is not None:
        sections.extend(_kit_sections(resolved_kit))

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


def write_pack(
    project: Path,
    *,
    include_sprint: str | None = None,
    include_philosophy: bool = False,
    kit_path: Path | None = None,
) -> Path:
    body = build_pack(
        project,
        include_sprint=include_sprint,
        include_philosophy=include_philosophy,
        kit_path=kit_path,
    )
    target = project / ".socrates-architect-pack.md"
    target.write_text(body)
    return target


# ---------------------------------------------------------------------------
# Optional preambles
# ---------------------------------------------------------------------------


def _philosophy_preamble() -> str:
    """A short, original stance summary written by socrates.

    Deliberately not copied from the 120x Operators Kit. Use --kit-path if
    you want the kit's own files embedded in the pack.
    """
    return """# 120x Architect / Builder stance (summary)

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


def _resolve_kit_path(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve() if explicit.exists() else None
    env = os.environ.get("SOCRATES_KIT_PATH")
    if env:
        candidate = Path(env).expanduser().resolve()
        return candidate if candidate.is_dir() else None
    return None


def _kit_sections(kit: Path) -> list[str]:
    sections: list[str] = []
    for name in KIT_FILES:
        path = kit / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace").strip()
        if not text:
            continue
        sections.append(f"# 120x Operators Kit: `{name}`\n\n{text}")
    return sections


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
