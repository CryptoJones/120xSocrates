# Changelog

All notable changes to 120xSocrates. Format follows [Keep a Changelog](https://keepachangelog.com/);
versions follow [SemVer](https://semver.org/). The version in `pyproject.toml` is the single
source of truth — the README badge reads it directly, and each release is tagged `vX.Y.Z`.

## [1.0.0] — 2026-06-10

The v1 release: the bugfix/reliability review wave merged, the codebase
restructured into a layered architecture, and the documentation brought into
verified agreement with the code. Generated kit output is byte-identical to
v0.8.0 — projects scaffolded by earlier versions are fully compatible.

### Fixed
- `decide`: multi-line decision text is collapsed to a single bullet so markdown bold rendering survives (#4).
- `timeline`: the decision-date regex anchors to the end of the bullet, so dates inside the decision body are no longer misread as the recording date (#7).
- `audit`: terminology check matches whole words (kebab-aware), ending false positives on substrings like `tier` in `outlier` (#10).
- `patterns review`: slug usage matching is word-boundary based, ending false positives on short slugs like `auth` in `author` (#6).
- `status`: extract detection reads each pattern file once and only credits an explicit `Source project` line, not any backtick mention (#11).
- `journal`: only canonical `YYYY-MM-DD.md` files count as entries; stray notes are ignored by `--show`/`--list` (#15).
- `onboard`: WELCOME.md derives the active sprint from the highest-numbered `NNN-*` folder instead of a hardcoded "001", and includes post-init decisions from `socrates decide`, freshest first (#9, #16).
- `prompting`: `$EDITOR` is parsed with `shlex` so quoted arguments survive, and the no-editor fallback respects the caller's input function (#12).

### Added
- `init` validates project slugs up front: path separators, `..` segments, absolute paths, and empty slugs are rejected with actionable messages before anything touches disk (#3).
- `scaffold`/`companyos` reject a regular-file target with a clear error instead of a confusing traceback (#13).
- Repo-level `AGENTS.md` (+ `CLAUDE.md`/`CODEX.md` adapters) and `docs/ARCHITECTURE.md` — the same conventions socrates scaffolds for its users.
- This changelog.

### Changed
- **Internal restructure** (no API change): the package is now eight modules grouped by role, reading in dependency layers — `support → kit → interview/audit → operate/patterns/synthesize → cli`. The public import surface (`from socrates120x import X`) is unchanged. Along the way the audit check class hierarchy became plain functions, duplicated color tables and atomic-write helpers were unified, and the architect preamble template was inlined.
- All file I/O pins `encoding="utf-8"` explicitly — behavior no longer depends on the platform locale (#8).

### Security / Reliability
- `pack --format html` output carries a strict Content-Security-Policy meta tag (no scripts, frames, or external resources), so previewing a bundle containing pasted third-party content cannot execute anything (#2).
- `.socrates-answers.json` and the patterns usage cache are written atomically (tempfile + `os.replace`); a kill mid-write can never corrupt them. A corrupt resume file produces a warning and a fresh start, not a traceback (#5, #14).
- `socrates decide` guards its read-modify-write with an advisory file lock — concurrent invocations can no longer silently lose a decision (#17).

## [0.8.0] — 2026-05-19
- `socrates pack --format md|html|xml`: XML section delimiters (Anthropic-style structural delimitation, ~5% token overhead) and full HTML output (optional `markdown` dependency, `pip install socrates120x[html]`).

## [0.7.0] — 2026-05-18
- `patterns review` usage cache: per-project mtime-segmented invalidation.
- Architect preamble moved to a template; `socrates decide` subcommand added.

## [0.6.0] — 2026-05-18
- Three honest-residual fixes from the v0.5 self-review.

## [0.5.0] — 2026-05-18
- Workflow automation: `timeline`, `ship`, `pack`.

## [0.4.0] — 2026-05-18
- Cross-project intelligence: `status`, `patterns review`, `audit --companyos`.

## [0.3.1] — 2026-05-18
- Three self-critique fixes.

## [0.3.0] — 2026-05-18
- `journal`, `companyos`, `extract`, `onboard`.

## [0.2.0] — 2026-05-18
- Subcommand split; `socrates audit`.

## Pre-history — 2026-05-18
- Initial scaffold: the interview CLI, `--editor` mode, running-list confirmation, inline defaults.
