# 120xSocrates

Interactive CLI that interrogates you Socratic-style and fills out the planning docs for a [120x Operators Kit](https://120x.ai) project.

[![Tests](https://github.com/CryptoJones/120xSocrates/actions/workflows/test.yml/badge.svg)](https://github.com/CryptoJones/120xSocrates/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg?logo=apache)](LICENSE)
[![Codeberg](https://img.shields.io/badge/Codeberg-CryptoJones%2F120xSocrates-2185D0?logo=codeberg&logoColor=white)](https://codeberg.org/CryptoJones/120xSocrates)
[![GitHub](https://img.shields.io/badge/GitHub-CryptoJones%2F120xSocrates-181717?logo=github&logoColor=white)](https://github.com/CryptoJones/120xSocrates)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v0.1.0-orange)]()

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

# run the interview against a fresh project
cd ~/Documents/120x-builds
socrates quarterly-rebates
```

Or run without installing:

```bash
python -m socrates120x quarterly-rebates
```

### Skipping the scaffold step

If you already ran `scaffold.sh` (or are re-running the interview against an existing project), pass `--no-scaffold`:

```bash
socrates quarterly-rebates --no-scaffold
```

### Resuming an interview

Answers are saved incrementally to `.socrates-answers.json` inside the project folder. If you Ctrl-C partway through, the next run picks up where you left off.

```bash
socrates quarterly-rebates --resume
```

## How the interview is structured

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
