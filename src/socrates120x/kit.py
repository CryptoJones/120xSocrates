"""The canonical 120x Operators Kit shapes.

Everything socrates WRITES lives here: the project scaffold tree (mirrors
the kit's scaffold.sh byte-for-byte), the planning-file renderers, and the
CompanyOS macro layer. If the kit's conventions ever change, this is the
one module that changes with them.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from socrates120x.support import atomic_write_text

# ─────────────────────────────────────────────────────────────────────────────
# scaffold — the canonical 120x Operators Kit project tree
# Mirrors the kit's scaffold.sh byte-for-byte so socrates is self-contained.
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_DIRS: tuple[str, ...] = (
    "docs",
    "planning",
    "planning/journal",
    "planning/meetings",
    "planning/sprints/001-discovery-architecture",
    "src",
    "tests",
    "scripts",
    "samples",
    "references",
)

# Files to create empty. socrates will populate most of these afterwards.
PROJECT_FILES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "README.md",
    ".gitignore",
    "docs/ARCHITECTURE.md",
    "docs/DATA_MODEL.md",
    "docs/API.md",
    "docs/PERMISSIONS.md",
    "docs/VALIDATION.md",
    "planning/STATE.md",
    "planning/DECISIONS.md",
    "planning/DOMAIN.md",
    "planning/RISKS.md",
    "planning/QUESTIONS.md",
    "planning/FILE_INVENTORY.md",
    "planning/journal/README.md",
    "planning/meetings/README.md",
    "planning/sprints/001-discovery-architecture/requirements.md",
    "planning/sprints/001-discovery-architecture/blueprint.md",
    "planning/sprints/001-discovery-architecture/acceptance.md",
    "planning/sprints/001-discovery-architecture/handoff-prompt.md",
    "src/README.md",
    "tests/README.md",
    "scripts/README.md",
    "samples/README.md",
    "references/README.md",
)


def scaffold(target: Path, *, overwrite: bool = False) -> list[Path]:
    """Create the 120x folder/file tree at *target*.

    Returns the list of files created (or that already existed).
    Raises FileExistsError if *target* already exists and ``overwrite`` is False.
    Raises NotADirectoryError if *target* already exists as a regular file —
    previously the call cascaded into a confusing "Cannot create directory"
    error from inside the PROJECT_FILES/PROJECT_DIRS loop. Catch it up-front so the operator
    gets an actionable message before any side effects.
    """
    if target.exists() and target.is_file():
        raise NotADirectoryError(
            f"Cannot scaffold into a regular file: {target}. "
            f"Pass a directory path (it will be created if missing)."
        )
    if target.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing path: {target}")

    target.mkdir(parents=True, exist_ok=overwrite)
    for d in PROJECT_DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    for f in PROJECT_FILES:
        path = target / f
        if not path.exists():
            path.touch()
        created.append(path)
    return created


# ─────────────────────────────────────────────────────────────────────────────
# render — write the answers dict into the 120x planning files
# ─────────────────────────────────────────────────────────────────────────────

def render_all(target: Path, answers: dict[str, Any], *, force: bool = False) -> list[Path]:
    """Write every planning/state/sprint file from *answers* into *target*.

    Returns the list of files actually written.

    By default an existing file that already has content is PRESERVED: a re-run
    (e.g. ``init --no-scaffold`` into a populated folder) must not clobber
    operator edits to living docs like STATE.md / DECISIONS.md. Freshly
    scaffolded files are empty, so the first render still writes them all.
    Pass ``force=True`` to regenerate everything from *answers*.
    """
    today = _dt.date.today().isoformat()
    ctx = {**answers, "today": today}

    files = {
        "AGENTS.md": _agents_md(ctx),
        "CLAUDE.md": _adapter_md("Claude Code"),
        "CODEX.md": _adapter_md("Codex"),
        "README.md": _readme_md(ctx),
        "planning/STATE.md": _state_md(ctx),
        "planning/DECISIONS.md": _decisions_md(ctx),
        "planning/DOMAIN.md": _domain_md(ctx),
        "planning/RISKS.md": _risks_md(ctx),
        "planning/QUESTIONS.md": _questions_md(ctx),
        "planning/FILE_INVENTORY.md": _file_inventory_md(ctx),
        "planning/journal/README.md": _journal_readme(),
        "planning/sprints/001-discovery-architecture/requirements.md": _sprint1_requirements(ctx),
        "planning/sprints/001-discovery-architecture/blueprint.md": _sprint1_blueprint(ctx),
        "planning/sprints/001-discovery-architecture/acceptance.md": _sprint1_acceptance(ctx),
        "planning/sprints/001-discovery-architecture/handoff-prompt.md": _sprint1_handoff(ctx),
        "docs/ARCHITECTURE.md": _stub("Architecture", ctx),
        "docs/DATA_MODEL.md": _stub("Data Model", ctx),
        "docs/API.md": _stub("API", ctx),
        "docs/PERMISSIONS.md": _stub("Permissions", ctx),
        "docs/VALIDATION.md": _stub("Validation Plan", ctx),
    }

    written: list[Path] = []
    for rel, body in files.items():
        path = target / rel
        if (
            not force
            and path.is_file()
            and path.read_text(errors="replace", encoding="utf-8").strip()
        ):
            continue  # preserve an existing file that already has real content
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, body)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------


def _bullet_list(items: list[str] | None, *, empty: str = "_(none recorded — add later)_") -> str:
    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)


def _para(text: str | None, *, empty: str = "_(to be written)_") -> str:
    if not text:
        return empty
    return text.strip()


def _g(ctx: dict[str, Any], key: str, default: Any = "") -> Any:
    val = ctx.get(key)
    if val is None or val == "":
        return default
    return val


# ---------------------------------------------------------------------------
# File renderers
# ---------------------------------------------------------------------------


def _agents_md(ctx: dict[str, Any]) -> str:
    name = _g(ctx, "project_name", "this project")
    client = _g(ctx, "client", "(client TBD)")
    tagline = _g(ctx, "tagline", "")
    tech = _g(ctx, "tech_stack", "TBD")
    return f"""# AGENTS.md — {name}

> Tool-agnostic router. **Read this first** before making any changes.

## What this project is

**{name}** — {tagline}

Client: **{client}**

Tech stack: **{tech}**

## Repo layout

```text
{name}/
├── AGENTS.md            ← you are here
├── CLAUDE.md            ← thin adapter for Claude Code
├── CODEX.md             ← thin adapter for Codex
├── README.md            ← human-facing overview
├── docs/                ← living architecture / data model / validation
├── planning/            ← the operating system for this project
│   ├── STATE.md         ← current sprint + next action
│   ├── DECISIONS.md     ← durable choices ("the house rules")
│   ├── DOMAIN.md        ← client terminology + workflow
│   ├── RISKS.md         ← known traps
│   ├── QUESTIONS.md     ← unresolved items
│   ├── FILE_INVENTORY.md
│   └── sprints/         ← one folder per sprint
├── src/                 ← application code
├── tests/               ← tests
├── scripts/             ← one-off / ops scripts
├── samples/             ← sample inputs (real or anonymised)
└── references/          ← supporting docs from the client
```

## How to start work

1. Read **`planning/STATE.md`** — what sprint we are in and what is next.
2. Read **`planning/DECISIONS.md`** and **`planning/DOMAIN.md`** — context that must not be re-derived.
3. Read the active sprint folder: **`planning/sprints/<active>/`** — `requirements.md`, `blueprint.md`, `acceptance.md`.
4. Confirm scope back to the operator **before** writing code.

## Rules

- Do not redefine scope. If a sprint requirement is ambiguous, add it to `planning/QUESTIONS.md` and stop.
- Do not invent business rules. They belong in `planning/DOMAIN.md` and `planning/DECISIONS.md`.
- Update `planning/STATE.md` at the end of every working session.
- New durable choices go to `planning/DECISIONS.md`.
- Validation is against real business expectations, not just passing tests — see `docs/VALIDATION.md`.

## Handoff principle

> The handoff is a folder, not a conversation.

The chat history is not the source of truth. The folder is.
"""


def _adapter_md(tool_name: str) -> str:
    return f"""# {tool_name} adapter

This file exists so that {tool_name} picks up project context automatically.

**Read `AGENTS.md` first.** Everything you need to know about this project — layout, rules, current state — is routed from there.

When updating state, edit `planning/STATE.md`, not this file.
"""


def _readme_md(ctx: dict[str, Any]) -> str:
    name = _g(ctx, "project_name", "Project")
    tagline = _g(ctx, "tagline", "")
    client = _g(ctx, "client", "")
    goal = _para(_g(ctx, "business_goal"))
    return f"""# {name}

{tagline}

Client: **{client}**

## Why this exists

{goal}

## Status

See [`planning/STATE.md`](planning/STATE.md) for the current sprint and next action.

## How to navigate

- **`AGENTS.md`** — start here. The tool-agnostic project router.
- **`planning/`** — the operating system (decisions, domain, risks, sprints).
- **`docs/`** — living architecture & validation reference.
- **`src/`** — implementation.

## Methodology

This project follows the [120x Operators Kit](https://120x.ai) Architect/Builder methodology — Architect thinks and writes the plan; Builder reads the plan and writes the code; the handoff is a folder, not a conversation.
"""


def _state_md(ctx: dict[str, Any]) -> str:
    current = _para(_g(ctx, "state_current"))
    nxt = _g(ctx, "state_next", "_(unset)_")
    blockers = _g(ctx, "state_blockers", [])
    return f"""# STATE — current moment

_Last updated: {ctx['today']}_

## Active sprint

**001 — Discovery & Architecture**

## Status

{current}

## Next action

{nxt}

## Blockers

{_bullet_list(blockers, empty="_(none)_")}

## Recently completed

- Project scaffolded via 120xSocrates ({ctx['today']}).
- Initial planning interview captured into this folder.
"""


def _decisions_md(ctx: dict[str, Any]) -> str:
    decisions = _g(ctx, "decisions", [])
    oos = _g(ctx, "out_of_scope", [])
    tech = _g(ctx, "tech_stack", "TBD")
    today = ctx["today"]

    # Each decision is stamped with the date it was captured. The trailing
    # `(YYYY-MM-DD)` is the convention `socrates timeline` reads to surface
    # decisions chronologically.
    decision_block = (
        "\n".join(f"- **{item} ({today})**" for item in decisions) if decisions else
        "_(no durable decisions captured yet)_"
    )
    return f"""# DECISIONS — the house rules

Durable choices future builders must respect. New decisions are appended; old ones are not deleted (they are crossed out and dated if reversed).

## Tech stack

- **{tech}**

## Decisions captured during Sprint 001 discovery

{decision_block}

## Explicitly out of scope

{_bullet_list(oos)}

## How to add a decision

When something gets decided in conversation, append it to the list above in the same format. **Always include the date** — `socrates timeline` reads the trailing `(YYYY-MM-DD)` to surface decisions chronologically:

```
- **<choice> — because <reason> (YYYY-MM-DD)**
```

If the decision is reversed, do not delete the line. Strike it through with `~~...~~` and add the new decision below with the date.
"""


def _domain_md(ctx: dict[str, Any]) -> str:
    users = _g(ctx, "users", [])
    process = _para(_g(ctx, "current_process"))
    terms = _g(ctx, "terminology", [])
    rules = _g(ctx, "business_rules", [])
    return f"""# DOMAIN — the client's world

The goal of this file is to make the Builder speak the **client's language**, not generic software language.

## Users / roles

{_bullet_list(users)}

## Current process (what happens today, manually)

{process}

## Terminology

{_bullet_list(terms, empty="_(no client-specific terms captured yet)_")}

## Business rules / invariants

{_bullet_list(rules, empty="_(no hard rules captured yet)_")}
"""


def _risks_md(ctx: dict[str, Any]) -> str:
    risks = _g(ctx, "risks", [])
    fragile = _para(_g(ctx, "fragile_inputs"), empty="_(no specific input fragility flagged)_")
    return f"""# RISKS — known traps

A short, living list. When a risk materialises, move it to `DECISIONS.md` with the mitigation chosen.

## Risks

{_bullet_list(risks)}

## Input fragility

{fragile}

## Always-on risks for any 120x project

- AI output is not source of truth. Numbers must trace back to data, documents, or human confirmation.
- Single-file overload — context must be split across the planning files, not crammed into one.
- Tool churn — the methodology must survive any specific agent going away.
"""


def _questions_md(ctx: dict[str, Any]) -> str:
    questions = _g(ctx, "open_questions", [])
    return f"""# QUESTIONS — unresolved items

When a question is answered, **move** the answer into `DECISIONS.md`, `DOMAIN.md`, or the relevant sprint file — do not leave answered questions sitting here.

## Open

{_bullet_list(questions, empty="_(no open questions — verify this is real, not laziness)_")}

## Closed (for traceability)

_(empty — answered questions get moved to their proper home and removed from here)_
"""


def _file_inventory_md(ctx: dict[str, Any]) -> str:
    inspect = _g(ctx, "sprint1_inspect", [])
    return f"""# FILE_INVENTORY — source files & assets

Track every external file (spreadsheets, PDFs, exports, screenshots) that informs this project. One row per file; do not lose track of where data came from.

## Files the Architect / Builder should inspect first

{_bullet_list(inspect, empty="_(none flagged yet — add as files arrive in `samples/` and `references/`)_")}

## Inventory

| File | Location | Source | Received | Notes |
|---|---|---|---|---|
| _example.xlsx_ | `samples/` | client | YYYY-MM-DD | _description_ |
"""


def _sprint1_requirements(ctx: dict[str, Any]) -> str:
    name = _g(ctx, "project_name", "this project")
    goal = _para(_g(ctx, "sprint1_goal"))
    tagline = _g(ctx, "tagline", "")
    return f"""# Sprint 001 — Discovery & Architecture | requirements

## Goal

{goal}

## User story

As the operator delivering **{name}** ({tagline}), I need a confirmed scope, a domain model in the client's terminology, and a file-level blueprint for Sprint 002 — so that the Builder can implement without re-deriving business rules.

## In scope

- Capture domain, decisions, risks, and open questions in `planning/`.
- Produce a Builder-ready blueprint for Sprint 002.
- Identify and stage sample input files in `samples/`.

## Out of scope

- Writing any application code.
- Locking in tech-stack components beyond what is already decided in `planning/DECISIONS.md`.

## Inputs

- Operator's domain knowledge (captured via 120xSocrates interview).
- Any client artifacts dropped into `samples/` and `references/`.

## Outputs

- Populated `planning/` directory.
- Stub `docs/` files ready for Sprint 002 expansion.
- Sprint 002 folder with `requirements.md`, `blueprint.md`, `acceptance.md`, `handoff-prompt.md`.
"""


def _sprint1_blueprint(ctx: dict[str, Any]) -> str:
    return """# Sprint 001 — Discovery & Architecture | blueprint

This sprint is documentation-only. No application code is written.

## Files to inspect

- `samples/` — every file the client has provided.
- `references/` — supporting docs (proposals, scope, decks).
- `planning/QUESTIONS.md` — anything still open.

## Files to create / modify

| Path | Purpose | Action |
|---|---|---|
| `planning/STATE.md` | Current moment | Confirm + tighten |
| `planning/DECISIONS.md` | Durable choices | Add any decisions made in Architect review |
| `planning/DOMAIN.md` | Client terminology + workflow | Expand from interview |
| `planning/RISKS.md` | Known traps | Add anything the Architect surfaces |
| `planning/QUESTIONS.md` | Unresolved | Move answered ones out |
| `planning/sprints/002-<name>/requirements.md` | Next sprint scope | Create |
| `planning/sprints/002-<name>/blueprint.md` | Next sprint plan | Create |
| `planning/sprints/002-<name>/acceptance.md` | Done criteria | Create |
| `planning/sprints/002-<name>/handoff-prompt.md` | Builder prompt | Create |
| `docs/DATA_MODEL.md` | Data model | First draft if structured data is involved |
| `docs/VALIDATION.md` | Validation plan | First draft of how trust will be proven |

## Step-by-step

1. Read every file in `samples/` and `references/`.
2. Review `planning/QUESTIONS.md` — escalate anything still open.
3. Update `planning/DOMAIN.md` with anything the samples taught you.
4. Draft Sprint 002 folder with concrete file-by-file build plan.
5. Confirm Sprint 002 acceptance criteria with the operator.
6. Update `planning/STATE.md` to point at Sprint 002.
"""


def _sprint1_acceptance(ctx: dict[str, Any]) -> str:
    crit = _g(ctx, "sprint1_acceptance", [])
    return f"""# Sprint 001 — Discovery & Architecture | acceptance

A sprint is **not** done because the folder exists. It is done when every criterion below is objectively true.

## Operator-defined criteria

{_bullet_list(crit, empty="_(none captured during interview — add before declaring sprint complete)_")}

## Always-on Sprint 001 criteria

- `planning/STATE.md` accurately reflects the current sprint and next action.
- `planning/DECISIONS.md` records every non-obvious choice made so far.
- `planning/DOMAIN.md` is written in the client's terminology (not generic software language).
- `planning/QUESTIONS.md` lists every unresolved item — none have been silently guessed at.
- Sprint 002 folder exists with all four files (`requirements.md`, `blueprint.md`, `acceptance.md`, `handoff-prompt.md`).
- The Builder agent could read this folder cold and start work without asking the operator clarifying questions.
"""


def _sprint1_handoff(ctx: dict[str, Any]) -> str:
    name = _g(ctx, "project_name", "this project")
    return f"""# Sprint 001 — Builder handoff prompt

Paste this into your Builder (Claude Code / Codex / Cursor / etc.) at the start of Sprint 002 work. Update the `[SPRINT_FOLDER]` placeholder.

```text
You are the Builder for {name}.

Before writing any code, read these files in order:

- AGENTS.md
- planning/STATE.md
- planning/DECISIONS.md
- planning/DOMAIN.md
- planning/RISKS.md
- planning/QUESTIONS.md
- planning/sprints/[SPRINT_FOLDER]/requirements.md
- planning/sprints/[SPRINT_FOLDER]/blueprint.md
- planning/sprints/[SPRINT_FOLDER]/acceptance.md

Then summarise back to me:

1. What you believe this sprint is supposed to accomplish.
2. The files you expect to modify.
3. The tests or validation steps you will run.
4. Any blockers or ambiguities.

Do not start implementation until I approve your summary. If anything in the
planning files contradicts itself, or is ambiguous, ADD a line to
planning/QUESTIONS.md and stop. Do not guess.
```
"""


def _journal_readme() -> str:
    return """# journal/

Append-only daily / weekly log. **Complements** `STATE.md` — does not replace it.

- `STATE.md` is the *current* moment — edited in place.
- `journal/YYYY-MM-DD.md` is *what happened* on that date — never edited later.

When you find yourself wondering "what changed between sprints 003 and 005?", this folder is the answer. `git log` is too noisy; STATE.md only holds the latest snapshot. The journal is the middle ground.

## Create today's entry

```bash
socrates journal
```

That creates `journal/YYYY-MM-DD.md` (with a short template) and opens it in `$EDITOR`. Save & quit to commit the entry.

## What to write

One short entry per working day, freeform. Things worth recording:

- What you decided that did not yet make it to `DECISIONS.md`.
- What surprised you (those become tomorrow's risks).
- What the client said in a call.
- What you tried that did not work — and why.

Future builders (human or agent) will read these in order. Optimize for skim-ability, not completeness.
"""


def _stub(title: str, ctx: dict[str, Any]) -> str:
    name = _g(ctx, "project_name", "this project")
    return f"""# {title} — {name}

_(Stub. Populate during Sprint 001 review or the relevant build sprint.)_

This file is part of the canonical 120x layout. It is created empty so that
the structure of the project is stable; content is added when the project
calls for it (data-heavy projects need `DATA_MODEL.md` and `VALIDATION.md`
early; API-only projects need `API.md` early; etc.).

See `AGENTS.md` for navigation and `planning/STATE.md` for what is happening
right now.
"""


# ─────────────────────────────────────────────────────────────────────────────
# companyos — the macro layer that wraps per-project builds
# Per the 120x philosophy, patterns / clients / pipeline live here, one
# level above builds/<project>/. The factory, not the house.
# ─────────────────────────────────────────────────────────────────────────────

COMPANYOS_DIRS: tuple[str, ...] = (
    "clients",
    "builds",
    "pipeline",
    "patterns",
    "content",
    "reference",
    "daily",
    "templates",
)


def scaffold_companyos(target: Path, *, overwrite: bool = False) -> list[Path]:
    """Create the CompanyOS macro layer at *target*. Returns files written.

    Raises NotADirectoryError if *target* is an existing regular file —
    previously `any(target.iterdir())` cascaded into NotADirectoryError
    from inside the boolean short-circuit, with a confusing traceback.
    Reject explicitly with an actionable message.
    """
    if target.exists() and target.is_file():
        raise NotADirectoryError(
            f"Cannot scaffold CompanyOS into a regular file: {target}. "
            f"Pass a directory path (it will be created if missing)."
        )
    if target.exists() and not overwrite and any(target.iterdir()):
        raise FileExistsError(
            f"Refusing to scaffold CompanyOS into non-empty path: {target}"
        )
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for d in COMPANYOS_DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)

    files = {
        "AGENTS.md": _companyos_agents_md(target.name),
        "CLAUDE.md": _companyos_adapter_md("Claude Code"),
        "CODEX.md": _companyos_adapter_md("Codex"),
        "README.md": _companyos_readme_md(target.name),
        "clients/README.md": _clients_readme(),
        "builds/README.md": _builds_readme(),
        "pipeline/README.md": _pipeline_readme(),
        "pipeline/prospects.md": _prospects_md(),
        "pipeline/proposals.md": _proposals_md(),
        "patterns/README.md": _patterns_readme(),
        "content/README.md": _content_readme(),
        "reference/README.md": _reference_readme(),
        "daily/README.md": _daily_readme(),
        "templates/README.md": _templates_readme(),
    }
    for rel, body in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, body)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _companyos_agents_md(name: str) -> str:
    return f"""# AGENTS.md — {name} (CompanyOS layer)

> Tool-agnostic router. **Read this first** before doing anything in this folder.

## What this is

The CompanyOS layer for `{name}`. It is the macro operating system that wraps every per-project build. Patterns, client context, pipeline, and content all live here. Per-project planning lives one level down inside `builds/<project>/`.

## Layout

```text
{name}/
├── AGENTS.md         ← you are here
├── CLAUDE.md         ← thin adapter for Claude Code
├── CODEX.md          ← thin adapter for Codex
├── README.md         ← human-facing overview
├── clients/          ← one folder per client (long-lived context, not project state)
├── builds/           ← per-project folders (each scaffolded by `socrates init`)
├── pipeline/         ← prospects, proposals, scoping notes
├── patterns/         ← extracted reusable patterns (the compounding asset)
├── content/          ← marketing assets, blog drafts, write-ups
├── reference/        ← docs, snippets, links, anything cross-project
├── daily/            ← daily / weekly operator notes
└── templates/        ← reusable scaffolds (proposal templates, sprint templates, etc.)
```

## Rules

- **Per-project state belongs inside `builds/<project>/`.** Do not pollute the CompanyOS layer with sprint-specific files.
- **Patterns are extracted, not invented.** Every file in `patterns/` should trace to a real project that produced it. Use `socrates extract` at the end of a sprint to capture one.
- **Clients are not projects.** A client may have several projects over time; `clients/<client>/` holds the durable client context (contacts, billing notes, working style). Each project that client commissions lives in `builds/`.

## Workflow

1. New lead → notes in `pipeline/prospects.md`.
2. Lead converts → folder in `clients/<client-name>/`.
3. Engagement starts → `socrates init builds/<project-slug>` from this directory.
4. Sprint ships → `socrates extract` writes a pattern candidate to `patterns/`.
5. Repeat. The factory gets sharper every project.
"""


def _companyos_adapter_md(tool: str) -> str:
    return f"""# {tool} adapter (CompanyOS layer)

**Read `AGENTS.md` first.** The CompanyOS routing lives there.

When working inside a specific build, descend into `builds/<project>/` and use that project's own `AGENTS.md`.
"""


def _companyos_readme_md(name: str) -> str:
    return f"""# {name}

CompanyOS layer — the macro operating system for a [120x.ai](https://120x.ai)-style software factory.

See [`AGENTS.md`](AGENTS.md) for the routing and the layout.

## Quick start

```bash
# scaffold a new project under this CompanyOS
cd builds
socrates init quarterly-rebates

# at the end of a sprint, extract reusable patterns
cd builds/quarterly-rebates
socrates extract
```
"""


def _clients_readme() -> str:
    return """# clients/

One folder per client. Durable client context only — not project state.

What belongs here:
- Contact info, billing details, working style notes
- A `meetings/` folder with call notes that are NOT tied to a single project
- Anything that survives a specific engagement

What does NOT belong here:
- Per-sprint state — that's in `builds/<project>/planning/STATE.md`
- Project requirements — that's in `builds/<project>/planning/sprints/`
"""


def _builds_readme() -> str:
    return """# builds/

One folder per project. Each is scaffolded by `socrates init` and has its own complete planning layer (`AGENTS.md`, `planning/`, `docs/`, etc.).

Do NOT put any non-project files here. Patterns extracted from a project go up to `../patterns/`, not into the project folder.
"""


def _pipeline_readme() -> str:
    return """# pipeline/

Pre-engagement: prospects, proposals, scoping notes, pricing sketches.

| File | Purpose |
|---|---|
| `prospects.md` | leads not yet qualified |
| `proposals.md` | drafts and sent proposals |

Once a prospect converts, the engagement moves to `clients/<name>/` + a new project in `builds/`.
"""


def _prospects_md() -> str:
    return """# Prospects

Leads not yet qualified. One entry per lead. Move to `proposals.md` when a proposal is in flight; move to `clients/<name>/` when signed.

## Template

```
### <Company Name> — <YYYY-MM-DD>
- **Contact:** name, role, email
- **Source:** referral / inbound / outbound
- **Asking about:** one-line problem statement
- **Status:** initial / qualifying / scoping / lost
- **Next action:** what I owe them
```
"""


def _proposals_md() -> str:
    return """# Proposals

Active and historical proposals. Keep one entry per project, even after the engagement ends — losses inform pricing.

## Template

```
### <Project> — <Client> — <YYYY-MM-DD>
- **Scope:** one-paragraph summary
- **Price:** $X (fixed / T&M / phased)
- **Timeline:** N weeks
- **Status:** drafted / sent / accepted / rejected / withdrawn
- **Lessons:** what we'd price differently next time
```
"""


def _patterns_readme() -> str:
    return """# patterns/

Extracted reusable patterns. **This is the compounding asset.** Every project should leave at least one pattern here.

Each pattern file follows the naming convention `<verb>-<noun>.md` (e.g. `validate-parsed-numbers.md`, `scope-data-projects.md`) and contains:

- **When this applies** — the situation that triggers using this pattern
- **When it does NOT apply** — failure modes
- **The pattern itself** — code, prompt, template, language
- **Source project** — the build folder where it was first extracted from

Pattern candidates (drafts) are written here by `socrates extract` and named `CANDIDATE-<slug>.md`. Promote a candidate to a real pattern by renaming it and tightening the content.
"""


def _content_readme() -> str:
    return """# content/

Marketing assets, blog posts, talks, write-ups. Anything customer-facing or audience-facing that's not a deliverable.

Suggested subfolders:
- `blog/` — drafts and published posts
- `talks/` — conference / podcast outlines
- `case-studies/` — anonymised project write-ups (Architect's call on what's anonymisable)
"""


def _reference_readme() -> str:
    return """# reference/

Cross-project knowledge: tool docs, snippets, vendor info, internal playbooks. Anything that's not specific to one client or one project.

When you find yourself copy-pasting the same snippet into multiple projects, it probably belongs here.
"""


def _daily_readme() -> str:
    return """# daily/

Operator notes — daily / weekly. Distinct from per-project journals (those live in `builds/<project>/planning/journal/`). This is the macro view: what was today's whole-portfolio shape?

Suggested format: one file per week, `YYYY-WW.md`.
"""


def _templates_readme() -> str:
    return """# templates/

Reusable scaffolds. Proposal templates, sprint templates, response-to-RFP templates, etc.

If you write a one-off and find yourself reaching for it again, copy it here and parameterise it.
"""
