# Architecture — 120xSocrates

The bird's-eye view. The README documents what each subcommand does for the
operator; this file documents how the code is shaped and which properties are
load-bearing.

## Design in one paragraph

socrates is a stdlib-only CLI that reads and writes one thing: the canonical
120x Operators Kit folder structure. Every subcommand is a function over that
structure — some write it (`init`, `companyos`, `decide`, `journal`,
`extract`), some read it and report (`audit`, `status`, `timeline`,
`patterns review`), some read it and synthesize derived documents (`onboard`,
`pack`, `ship`). The kit's shapes are defined in exactly one module, and
everything else depends on them, never the reverse.

## Module layers

Eight modules, dependencies flowing strictly downward. No module imports from
a layer above it; `cli` is the only module that imports from everywhere.

```text
            ┌──────────────────────────────────────────────┐
  layer 4   │                    cli                       │  argparse + dispatch
            └──┬────────┬───────────┬──────────┬───────┬───┘
            ┌──▼─────┐ ┌▼────────┐ ┌▼────────┐ ┌▼──────▼──┐
  layer 3   │operate │ │patterns │ │synthesize│ │(commands)│  decide journal timeline
            └──┬───┬─┘ └┬──────┬─┘ └──────────┘ │          │  ship status / extract
            ┌──▼┐ ┌▼────▼───┐ ┌▼─────────┐      │          │  review / onboard pack
  layer 2   │   │ │interview│ │  audit   │◄─────┘          │
            │   │ └────┬────┘ └─┬──────┬─┘                 │
            │   │      │        │      │                   │
            ┌───▼──────▼────┐ ┌─▼──────▼─┐
  layer 1   │    support    │ │   kit    │   the 120x shapes
            └───────────────┘ └──────────┘
```

| Module | Role | May import from |
|---|---|---|
| `support.py` | terminal colors, atomic file I/O, prompting primitives. Zero 120x knowledge — could be vendored into any CLI. | stdlib only |
| `kit.py` | the canonical 120x shapes: project scaffold tree, planning-file renderers, CompanyOS macro layer. The kit's conventions live **only** here. | stdlib only |
| `interview.py` | `Question` sets + the resumable `Interview` runner | support |
| `audit.py` | findings model (`Severity`, `Finding`, `AuditReport`), all project + CompanyOS checks as plain functions, runner, report formatting | support, kit, patterns¹ |
| `operate.py` | daily rituals: decide, journal, timeline, ship, status | support, audit |
| `patterns.py` | the pattern lifecycle: extract (interview-driven creation) + review (drift detection with an mtime-segmented usage cache) | support, interview |
| `synthesize.py` | derived documents: onboard (WELCOME.md) + pack (Architect bundle, md/xml/html) | stdlib only |
| `cli.py` | argument parsing, target validation, dispatch — the main file; no business logic | everything above |

¹ `audit` imports the pattern-file source-line regex from `patterns`, which
owns the pattern file format. This is the one cross-layer edge; it points
sideways, not upward, and exists so the format is defined once.

`__init__.py` re-exports the public surface, so callers (and the test suite)
use `from socrates120x import X` without coupling to the internal layout.
Carving, merging, or renaming modules must not change that import surface.

## Naming

Three names, one thing, all intentional: **120xSocrates** is the repo and
human-facing name, **socrates120x** is the Python distribution/package (a
leading digit is not a valid Python identifier), and **socrates** is the
installed command (short, because operators type it daily). Don't "fix" this.

## Invariants (the load-bearing properties)

1. **Kit compatibility.** Generated artifacts — scaffold tree, rendered
   planning files, CompanyOS layer — match the 120x Operators Kit
   byte-for-byte. Refactors are verified by diffing generated output against
   the previous version; behavior changes to any template are deliberate,
   never incidental.
2. **Zero runtime dependencies.** stdlib only. `pack --format html` needs the
   optional `markdown` package and fails with an install hint, not a
   traceback.
3. **No false positives in audit.** A noisy audit gets ignored. Checks err
   toward INFO; WARNING and ERROR are reserved for things that are wrong by
   definition. Word-boundary matching (not substring) wherever slugs or terms
   are searched.
4. **Crash-safe writes.** Anything an operator would cry over losing —
   `.socrates-answers.json`, `DECISIONS.md`, the patterns usage cache — is
   written atomically (tempfile + `os.replace`). `socrates decide` guards its
   read-modify-write with an advisory flock so concurrent invocations cannot
   silently drop a decision (no-ops on platforms without `fcntl`).
5. **Locale independence.** Every `read_text`/`write_text` pins
   `encoding="utf-8"`.
6. **Exit codes are API.** `0` clean, `1` findings/failures (CI-able),
   `2` invocation error, `130` interrupted interview.

## Data files on disk

| File | Written by | Read by |
|---|---|---|
| `.socrates-answers.json` | init interview (incremental, atomic) | onboard, status, audit (client ref), ship |
| `.socrates-extract-answers.json` | extract interview | ship, status (in-progress signal) |
| `.socrates-audit.json` | the operator (by hand) | audit (`scaffold-shape` ignore list) |
| `patterns/.usage-cache.json` | patterns review (atomic) | patterns review (per-project mtime invalidation) |
| `.socrates-architect-pack.<ext>` | pack | the operator (paste into Architect chat) |

## Testing strategy

The suite (200+ tests) pins **behavior**, not implementation: tests build real
project trees in `tmp_path`, run the public functions, and assert on the files
and findings produced. That is what made two full structural refactors (a
single-file collapse and this carve) safe to execute mechanically — the tests
survived both with only import-path edits.

CI runs `pytest`, `ruff check .`, and `mypy src` (strict) on Python 3.10–3.12,
on both GitHub Actions and Woodpecker (Codeberg).

## History

The current shape is the third iteration, each verified byte-identical to the
last: an organically grown 20-module tree → a single-file collapse (which
deleted the ceremony: an ABC check hierarchy, four copies of the color table,
duplicated atomic-write helpers) → this 8-module carve, which kept the
deletions and restored navigability by grouping code by role.
