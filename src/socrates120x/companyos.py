"""The CompanyOS layer — the macro operating system that wraps per-project builds.

Per the 120x philosophy, every project produces three assets: the shipped
system, the preserved blueprint (the project folder), and the extracted
pattern (which compounds across projects). The CompanyOS layer is where
those patterns live. Without it, the per-project layer is a soup of
unrelated folders and the "factory gets sharper" claim stays aspirational.

This module ships the minimal macro skeleton — folders + index files —
that downstream `socrates extract` runs can write into.
"""

from __future__ import annotations

from pathlib import Path

DIRS: tuple[str, ...] = (
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
    """Create the CompanyOS macro layer at *target*. Returns files written."""
    if target.exists() and not overwrite and any(target.iterdir()):
        raise FileExistsError(
            f"Refusing to scaffold CompanyOS into non-empty path: {target}"
        )
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for d in DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)

    files = {
        "AGENTS.md": _agents_md(target.name),
        "CLAUDE.md": _adapter_md("Claude Code"),
        "CODEX.md": _adapter_md("Codex"),
        "README.md": _readme_md(target.name),
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
        path.write_text(body)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _agents_md(name: str) -> str:
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


def _adapter_md(tool: str) -> str:
    return f"""# {tool} adapter (CompanyOS layer)

**Read `AGENTS.md` first.** The CompanyOS routing lives there.

When working inside a specific build, descend into `builds/<project>/` and use that project's own `AGENTS.md`.
"""


def _readme_md(name: str) -> str:
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
