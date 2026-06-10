# AGENTS.md — 120xSocrates

> Tool-agnostic router. **Read this first** before making any changes.
> Yes, this is the same file this tool scaffolds for its users — we eat the dog food.

## What this project is

**120xSocrates** — interactive CLI that interrogates the operator Socratic-style and fills out the planning docs for a [120x Operators Kit](https://120x.ai) project.

Tech stack: **Python 3.10+, stdlib only (zero runtime dependencies)**.

## Repo layout

```text
120xSocrates/
├── AGENTS.md              ← you are here
├── CLAUDE.md / CODEX.md   ← thin adapters routing to this file
├── README.md              ← user-facing docs (subcommands, flags, examples)
├── docs/ARCHITECTURE.md   ← module layering, dependency rule, invariants
├── pyproject.toml         ← packaging, ruff/mypy/pytest config
├── src/socrates120x/      ← the package — eight modules, layered (see docs/)
└── tests/                 ← pytest suite; behavior-pinning, no mocks of the filesystem
```

## How to start work

1. Read `docs/ARCHITECTURE.md` — the module layers and the dependency rule.
2. Find the owning module for your change (grouped by role, not by subcommand).
3. Write or update the test first; the suite pins behavior, not implementation.

## Rules

- **Kit compatibility is a hard invariant.** The folder trees and planning files socrates writes must match the 120x Operators Kit scaffold byte-for-byte. If a change alters any generated artifact, that is a breaking change and must be deliberate.
- **Zero runtime dependencies.** The stdlib is the dependency budget. Optional extras (like `markdown` for `pack --format html`) must stay optional and degrade with an actionable error.
- **No false positives in audit checks.** A check that fires on a healthy project gets the whole audit ignored. When in doubt, emit INFO.
- **Dependencies flow downward only**: `support → kit → interview/audit → subcommands → cli`. No module imports from a layer above it.
- **Run everything CI runs before committing**: `pytest`, `ruff check .`, `mypy src` (strict).
- All file I/O is explicit UTF-8; files that operators depend on (answers, DECISIONS.md, caches) are written atomically.

## Mirrors

Pushed to both [GitHub](https://github.com/CryptoJones/120xSocrates) and [Codeberg](https://codeberg.org/CryptoJones/120xSocrates). Codeberg is the source of truth on divergence.
