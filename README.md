# 120xSocrates

Interactive CLI that interrogates you Socratic-style and fills out the planning docs for a [120x Operators Kit](https://120x.ai) project.

[![Tests](https://github.com/CryptoJones/120xSocrates/actions/workflows/test.yml/badge.svg)](https://github.com/CryptoJones/120xSocrates/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg?logo=apache)](LICENSE)
[![Codeberg](https://img.shields.io/badge/Codeberg-CryptoJones%2F120xSocrates-2185D0?logo=codeberg&logoColor=white)](https://codeberg.org/CryptoJones/120xSocrates)
[![GitHub](https://img.shields.io/badge/GitHub-CryptoJones%2F120xSocrates-181717?logo=github&logoColor=white)](https://github.com/CryptoJones/120xSocrates)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v0.5.0-orange)]()

> Mirrored on both [GitHub](https://github.com/CryptoJones/120xSocrates) and
> [Codeberg](https://codeberg.org/CryptoJones/120xSocrates). Issues filed on
> either are welcome; commits are pushed to both.

---

## What it does

The [120x Operators Kit](https://120x.ai) ships a `scaffold.sh` that creates an empty project skeleton — folders for `planning/`, `docs/`, `src/`, plus 20+ blank markdown files (`AGENTS.md`, `STATE.md`, `DECISIONS.md`, `DOMAIN.md`, `RISKS.md`, `QUESTIONS.md`, sprint requirements/blueprint/acceptance, etc.) that the operator is supposed to fill in with content from an "Architect" chat session.

**120xSocrates is the part that actually fills them in.**

Instead of copy-pasting from a browser chat back into your code editor, `socrates` runs at the command line, asks you a structured series of Socratic questions about the project, and writes the answers directly into every planning file in the right shape. One terminal session, no chat thread to manage, no folder of blank `.md`s left behind.

In a single command it will:

1. Run the standard 120x scaffold (creating the folder tree and blank files), or use an existing one.
2. Walk you through ~30 questions covering business goal, users, workflow, data, risks, decisions, and Sprint 001 scope.
3. Write the answers into the canonical 120x planning files using the kit's conventions.
4. Print a punch list of any unresolved questions and what to send to the Architect next.

## Quick start

```bash
# install from source
git clone https://github.com/CryptoJones/120xSocrates.git
cd 120xSocrates
pip install -e .

# (optional) scaffold the macro layer once
socrates companyos ~/Documents/120x

# scaffold + interview a fresh project
cd ~/Documents/120x/builds
socrates init quarterly-rebates

# every working day, log what happened
cd quarterly-rebates
socrates journal

# verify the planning files stayed consistent (good in CI)
socrates audit

# generate a 60-second briefing for new collaborators
socrates onboard

# at the end of a sprint, capture a reusable pattern
socrates extract
```

## Subcommands

`socrates` ships ten subcommands. They are designed to be composable —
each one operates on a 120x folder produced by `socrates init` or
`socrates companyos`.

**Per-project commands** (run inside a single `builds/<project>/`):

| Subcommand | One-liner |
|---|---|
| `socrates init <slug>` | scaffold a project and interview the operator |
| `socrates audit [path]` | verify planning files for internal consistency |
| `socrates onboard [path]` | produce a 60-second WELCOME.md from existing planning files |
| `socrates journal [path]` | open today's `planning/journal/YYYY-MM-DD.md` entry |
| `socrates extract [path]` | sprint-close interview to capture a reusable pattern |
| `socrates timeline [path]` | chronological feed of journal entries, sprints, and dated decisions |
| `socrates ship [path]` | sprint-close pre-flight: audit + journal + extract + state freshness |
| `socrates pack [path]` | assemble an Architect input bundle for browser chat |

**Macro-level commands** (run at the CompanyOS root):

| Subcommand | One-liner |
|---|---|
| `socrates companyos <path>` | scaffold the macro layer that wraps per-project builds |
| `socrates status [path]` | one-screen health dashboard for every project in a CompanyOS |
| `socrates patterns review [path]` | scan `patterns/` for stale candidates, orphans, and unused entries |
| `socrates audit --companyos [path]` | macro-level audit (orphan builds/clients/patterns, stale proposals) |

### `socrates init <slug>` — interview a new project

Scaffolds the 120x folder tree and walks the operator through the Socratic interview, then writes the planning files.

| Flag | Effect |
|---|---|
| `--base PATH` | parent dir for the project folder (default: cwd) |
| `--no-scaffold` | skip the scaffold step (folder must exist) |
| `--resume` | resume a partially-completed interview |
| `--no-render` | save answers but skip writing the `.md` files |
| `--editor` | use `$EDITOR` for multi-line answers |

Answers are saved incrementally to `.socrates-answers.json` inside the project folder, so Ctrl-C is safe and `--resume` picks up where you left off.

#### Editor mode for prose answers

For longer paragraphs, pass `--editor` and socrates will open `$EDITOR` (honouring `$VISUAL`, falling back to `nano`/`vim`/`vi`) with a tempfile per multi-line question. Comment lines (`#`-prefixed) are stripped on save; an empty file accepts the question's default.

### `socrates audit [path]` — verify an existing project

Scans a populated 120x folder for structural and content issues. Exits non-zero when errors are found, so it slots cleanly into CI:

```bash
socrates audit                          # audit the current folder
socrates audit ./quarterly-rebates      # audit a specific project
socrates audit . --strict               # treat warnings as errors
socrates audit . --json                 # machine-readable output
```

The audit runs eight checks; each was chosen to be high-signal with **zero tolerance for false positives** (a noisy audit gets ignored):

| Check | Severity | What it catches |
|---|---|---|
| `required-files` | ERROR | one of the canonical planning files is missing |
| `sprint-folders` | ERROR | a sprint folder is malformed (bad name, missing one of the 4 required files) |
| `scaffold-shape` | WARNING | a scaffold file was pruned (allowed, but worth noting) |
| `adapter-routing` | WARNING | `CLAUDE.md` / `CODEX.md` does not point to `AGENTS.md` |
| `acceptance-weasels` | WARNING | acceptance criteria use vague phrases (`TBD`, `as needed`, `robust enough`, …) |
| `state-freshness` | WARNING | `STATE.md` has not been touched in 30+ days |
| `always-on-risks` | INFO | `RISKS.md` is missing the kit's "AI is not source of truth" reminder |
| `terminology-used` | INFO | a term defined in `DOMAIN.md` is not used anywhere else (dead-weight definition) |

Exit codes: `0` clean (info-only is still clean), `1` errors present (or warnings with `--strict`), `2` invocation error.

### `socrates onboard [path]` — synthesize WELCOME.md

Reads the existing planning files (STATE / DECISIONS / RISKS / QUESTIONS) and writes a one-minute briefing as `WELCOME.md` in the project root. **Pure synthesis** — no interview, no LLM, no third-party calls. Designed for the case where a new collaborator (human or agent) walks in cold.

```bash
socrates onboard                       # write WELCOME.md in cwd
socrates onboard ./quarterly-rebates   # write into a specific project
socrates onboard . --stdout            # print to stdout instead of writing
```

The synthesized WELCOME.md contains:

- Project tagline, client, tech stack
- Active sprint, current status, next action
- The 3 most load-bearing decisions, 3 explicitly out-of-scope items
- The 3 most prominent risks and open questions
- A pointer to the active sprint folder and the three files to read next

The output is auto-generated. Re-run `socrates onboard` whenever planning state shifts.

### `socrates journal [path]` — append-only daily log

Creates today's `planning/journal/YYYY-MM-DD.md` entry (with a short template) and opens `$EDITOR` so you can fill it in. The journal **complements** `STATE.md`: STATE is the rolling snapshot, journal entries are immutable historical fragments.

```bash
socrates journal                       # create + open today's entry
socrates journal --show                # print the latest entry
socrates journal --list                # list all entries, oldest first
```

When you find yourself wondering "what changed between sprints 003 and 005?", this folder is the answer.

### `socrates extract [path]` — capture a reusable pattern

A sprint-close interview that walks the operator through capturing one reusable pattern from the project that just shipped. The 120x methodology promises three deliverables (the shipped system, the preserved blueprint, and **the extracted pattern**); the third is the one most often skipped.

```bash
socrates extract                       # interview, write patterns/CANDIDATE-<slug>.md
socrates extract --editor              # open $EDITOR for the pattern body (recommended)
socrates extract --patterns-dir ../patterns/   # explicit target
```

Auto-detection: if the project sits inside a CompanyOS layout (`builds/<project>/`), the pattern is written to the sibling `patterns/` directory so it lives at the macro level where it can compound across projects. Otherwise a local `patterns/` directory inside the project is used.

Pattern files are named `CANDIDATE-<slug>.md`. Promote a candidate to a real pattern by dropping the `CANDIDATE-` prefix **only after** it has worked on at least one additional project.

### `socrates companyos <path>` — scaffold the macro layer

Creates the CompanyOS skeleton: `clients/`, `builds/`, `pipeline/`, `patterns/`, `content/`, `reference/`, `daily/`, `templates/`, plus an `AGENTS.md` router that points each subfolder at its role.

```bash
socrates companyos ~/Documents/120x
```

Per the 120x philosophy, the CompanyOS is the macro operating system that wraps every per-project build. Per-project state lives in `builds/<project>/`; long-lived assets (extracted patterns, client context, pipeline notes) live at the CompanyOS root. Use this once when setting up the factory; thereafter `socrates init builds/<slug>` from inside it.

## How the `init` interview is structured

The questions follow the 120x Operators Kit's own document layout, so each answer maps to exactly one place in the resulting folder:

| Section | Asks about | Populates |
|---|---|---|
| Project Identity | name, client, tagline, tech stack | `README.md`, `AGENTS.md` |
| Domain | client terminology, users, workflow, current process | `planning/DOMAIN.md` |
| Decisions | architectural choices already made, things explicitly out of scope | `planning/DECISIONS.md` |
| Risks | known traps, fragile inputs, scope creep flags | `planning/RISKS.md` |
| Open Questions | things you don't know yet | `planning/QUESTIONS.md` |
| Sprint 001 | discovery goal, acceptance criteria, handoff prompt | `planning/sprints/001-discovery-architecture/*.md` |
| State | current status, next action | `planning/STATE.md` |

Questions you cannot answer are written verbatim to `QUESTIONS.md` rather than guessed — that's the Socratic part. The Architect ([Claude Chat](https://claude.ai) or ChatGPT) can then pick up the question list directly.

## Requirements

- Python 3.10+. No third-party dependencies for runtime; just the standard library.

The folder structure socrates produces matches the [120x Operators Kit](https://120x.ai) scaffold byte-for-byte, but socrates does not require the kit to be installed locally — the structure is baked in.

## Why this exists

The [Operators Kit](https://120x.ai) is great. The four-step workflow is great. But Step 4 — "have the Builder populate the empty files from the Architect's pasted output" — is the friction point: it requires a browser chat session and a paste-back loop.

For projects where the operator already has the answers in their head (and most consulting work is like this), going through a chat thread to produce the planning pack is overkill. 120xSocrates collapses that loop into a single terminal interview that produces the same output, with the same structure, in less time.

## License

Apache 2.0. See [LICENSE](LICENSE).

Not affiliated with or endorsed by 120x.ai — this is an independent tool that consumes the publicly-published Operators Kit.

Proudly Made in Nebraska. Go Big Red! 🌽 https://xkcd.com/2347/
