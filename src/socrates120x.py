"""120xSocrates — the whole tool in one file.

Interactive CLI that interrogates you Socratic-style and fills out the
planning docs for a 120x Operators Kit project. Pure stdlib, no runtime
dependencies. The file reads top to bottom in the order a project lives:

  atomic       tempfile+rename writes and flock-guarded read-modify-write
  prompting    terminal Q&A primitives (Question, ask, $EDITOR mode)
  interview    the init question set + resumable runner
  scaffold     the canonical 120x project tree (mirrors the kit's scaffold.sh)
  render       answers dict -> populated planning .md files
  companyos    the macro layer that wraps per-project builds
  audit        consistency checks for projects and CompanyOS roots
  decide       append a dated decision to DECISIONS.md
  journal      append-only daily log entries
  onboard      synthesize a 60-second WELCOME.md briefing
  extract      sprint-close interview that captures a reusable pattern
  timeline     chronological feed of journal entries / sprints / decisions
  ship         sprint-close pre-flight checklist
  status       CompanyOS health dashboard
  patterns     patterns/ folder review (stale / orphan / unused)
  pack         assemble the Architect input bundle (md / xml / html)
  cli          argparse wiring for the `socrates` command
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape as _xml_escape

try:
    __version__ = version("socrates120x")
except PackageNotFoundError:
    # Running from a source checkout that was never installed.
    __version__ = "0.0.0+unknown"


# ─────────────────────────────────────────────────────────────────────────────
# terminal colors
# One ANSI table for the whole program; every formatter routes through
# _color() and emits plain text when stdout is not a TTY.
# ─────────────────────────────────────────────────────────────────────────────

_COLORS = {
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "cyan": "\033[36m",
    "magenta": "\033[35m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}
_RESET = "\033[0m"


def _color(text: str, color: str, use_color: bool) -> str:
    if not use_color or color not in _COLORS:
        return text
    return f"{_COLORS[color]}{text}{_RESET}"


def _dim(text: str, use_color: bool) -> str:
    return _color(text, "dim", use_color)


# ─────────────────────────────────────────────────────────────────────────────
# atomic file I/O — shared write-safety helpers
# Atomic writes (tempfile + os.replace) and flock-guarded read-modify-write
# (POSIX advisory lock; silent no-op where fcntl is unavailable). decide
# routes through locked_read_modify_write; interview saves atomically.
# ─────────────────────────────────────────────────────────────────────────────

def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically.

    Writes to a same-directory ``<name>.tmp`` then ``os.replace`` onto
    the final path. The tempfile lives in the same directory so the
    rename is always within the same filesystem (i.e. always atomic).
    Cleans up the tempfile on both the happy path and the exception
    path so we never leave a stranded ``.tmp`` for the next run to
    wonder about.

    Encoding defaults to UTF-8 to match the project-wide
    locale-independence policy.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def locked_read_modify_write(
    path: Path,
    mutate: Callable[[str], str],
    *,
    encoding: str = "utf-8",
) -> None:
    """Exclusive read-modify-write on *path*, atomic on write.

    ``mutate`` is called with the file's current text; its return value
    gets written back via :func:`atomic_write_text`.

    Lock strategy. We can NOT lock *path* directly: atomic_write_text
    renames a tempfile onto *path*, which orphans the old inode and the
    flock with it. A second worker would acquire the (now-stale)
    old-inode lock and read pre-rename content, producing a silent
    lost-update — the exact bug we're trying to prevent.

    Instead we lock a sibling ``.<name>.lock`` file whose inode is
    stable across renames. Both workers ``open(lockfile, O_CREAT)`` and
    ``flock(LOCK_EX)`` on it; the second blocks until the first releases.
    The lock is held for the ENTIRE read → mutate → atomic-write cycle,
    so the second worker always reads what the first one wrote.

    Non-POSIX: ``fcntl`` is unavailable; the lock silently no-ops,
    matching the pre-fix unlocked behavior — no regression. The atomic
    write half still applies, so a mid-write SIGINT doesn't corrupt
    *path* even without serialization.

    *path* must exist; the caller's existence check + actionable error
    is much better UX than a stat error from inside the lock attempt.
    """
    if not path.is_file():
        raise FileNotFoundError(path)

    lock_path = path.with_name("." + path.name + ".lock")
    # O_CREAT so the first invocation can create it; subsequent runs
    # open the same inode and the lock contends naturally.
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _flock_exclusive_or_noop_fd(lock_fd)
        try:
            # Read AFTER acquiring the lock — if a previous holder just
            # released, we want the content they wrote, not whatever
            # was there when we started waiting.
            current = path.read_text(encoding=encoding)
            new_text = mutate(current)
            atomic_write_text(path, new_text, encoding=encoding)
        finally:
            _flock_release_or_noop_fd(lock_fd)
    finally:
        os.close(lock_fd)


# ---------------------------------------------------------------------------
# POSIX flock — silently no-ops where unavailable. Module-private.
# Operate on raw file descriptors so we can avoid keeping a Python file
# object alive around the locked region (cleaner cleanup).
# ---------------------------------------------------------------------------


def _flock_exclusive_or_noop_fd(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover — Windows / embedded Pythons
        return
    fcntl.flock(fd, fcntl.LOCK_EX)


def _flock_release_or_noop_fd(fd: int) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover
        return
    fcntl.flock(fd, fcntl.LOCK_UN)


# ─────────────────────────────────────────────────────────────────────────────
# prompting — reusable terminal Q&A primitives
# Shared by every subcommand that needs structured question-and-answer flow
# (init, extract). Nothing here knows about the 120x methodology — pure I/O.
# ─────────────────────────────────────────────────────────────────────────────

QuestionType = Literal["line", "multiline", "list"]

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


@dataclass(frozen=True)
class Question:
    """One question presented to the operator."""

    key: str
    prompt: str
    section: str
    help: str = ""
    type: QuestionType = "line"
    required: bool = False
    default: str = ""


def is_interactive() -> bool:
    return sys.stdin.isatty()


def print_section_banner(section: str, output_fn: OutputFn) -> None:
    output_fn("")
    output_fn(f"━━━ {section} ━━━")


def show_existing(value: Any, output_fn: OutputFn) -> None:
    if isinstance(value, list):
        output_fn("  (already answered:)")
        for item in value:
            output_fn(f"    - {item}")
    else:
        output_fn(f"  (already answered: {value!r})")


def confirm_change(input_fn: InputFn, output_fn: OutputFn) -> bool:
    try:
        reply = input_fn("  Re-answer? [y/N] ").strip().lower()
    except EOFError:
        return False
    return reply in ("y", "yes")


def ask(
    q: Question,
    i: int,
    total: int,
    input_fn: InputFn,
    output_fn: OutputFn,
    *,
    editor: bool = False,
) -> Any:
    output_fn("")
    output_fn(f"[{i}/{total}] {q.prompt}")
    if q.help:
        for line in q.help.splitlines():
            output_fn(f"   • {line}")
    if q.default:
        output_fn(f"   (default: {q.default})")

    if q.type == "list":
        return _ask_list(input_fn, output_fn, q)
    if q.type == "multiline":
        if editor:
            return _ask_multiline_editor(output_fn, q, input_fn=input_fn)
        return _ask_multiline(input_fn, output_fn, q)
    return _ask_line(input_fn, output_fn, q)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def _ask_line(input_fn: InputFn, output_fn: OutputFn, q: Question) -> str:
    suffix = f" [default: {q.default!r}]" if q.default else ""
    while True:
        try:
            raw = input_fn(f"   ›{suffix} ").strip()
        except EOFError:
            raw = ""
        if not raw and q.default:
            return q.default
        if not raw and q.required:
            output_fn("   (this one is required — please answer)")
            continue
        return raw


def _ask_multiline(input_fn: InputFn, output_fn: OutputFn, q: Question) -> str:
    output_fn("   (multi-line — finish with a single '.' on its own line)")
    lines: list[str] = []
    while True:
        prompt = "   …  " if lines else "   ›  "
        try:
            line = input_fn(prompt)
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    text = "\n".join(lines).rstrip()
    if not text and q.default:
        output_fn("   (using default)")
        return q.default
    if not text and q.required:
        output_fn("   (this one is required — try again)")
        return _ask_multiline(input_fn, output_fn, q)
    return text


def _ask_multiline_editor(
    output_fn: OutputFn, q: Question, *, input_fn: InputFn = input
) -> str:
    """Open $EDITOR for a multiline answer; fall back to inline prompt if
    no editor is configured.

    The fallback used to hardcode the builtin ``input`` instead of the
    caller's ``input_fn``, which silently bypassed any input mock in
    tests — and on real runs meant the operator typed into stdin without
    seeing the prompt their parent shell expected. Now the parameter is
    threaded through so the fallback respects whatever input mechanism
    the caller wired up.
    """
    editor = editor_command()
    if not editor:
        output_fn("   (no $EDITOR set and no fallback found — falling back to inline prompt)")
        return _ask_multiline(input_fn, output_fn, q)

    header = f"""# {q.prompt}
# Lines starting with '#' are ignored. Save & quit to submit your answer.
# An empty file (or a file with only comments) accepts the default if one
# exists, or re-prompts otherwise.
"""
    if q.default:
        header += f"# Default: {q.default}\n"
    header += "#\n"

    with tempfile.NamedTemporaryFile(
        mode="w+",
        prefix=f"socrates-{q.key}-",
        suffix=".md",
        delete=False,
    ) as tf:
        tf.write(header)
        tmp_path = Path(tf.name)

    try:
        output_fn(f"   (opening {editor[0]} — save & quit to submit)")
        subprocess.run([*editor, str(tmp_path)], check=True)
        raw = tmp_path.read_text(encoding="utf-8")
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()

    body = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("#")
    ).strip()

    if not body and q.default:
        output_fn("   (empty — using default)")
        return q.default
    if not body and q.required:
        output_fn("   (this one is required — re-opening editor)")
        return _ask_multiline_editor(output_fn, q, input_fn=input_fn)
    return body


def _ask_list(input_fn: InputFn, output_fn: OutputFn, q: Question) -> list[str]:
    output_fn("   (one item per line — empty line to finish list)")
    items: list[str] = []
    while True:
        try:
            line = input_fn(f"   {len(items) + 1:>2}.  ").strip()
        except EOFError:
            break
        if not line:
            break
        items.append(line)
        output_fn(f"        ✓ ({len(items)} so far)")
    if items:
        output_fn(f"   ↳ captured {len(items)} item{'s' if len(items) != 1 else ''}")
    return items


def editor_command() -> list[str] | None:
    """Resolve the editor to invoke. Honour $VISUAL / $EDITOR, else fall back.

    Use shlex.split so quoted args in $EDITOR survive — e.g.
        EDITOR="emacsclient -a 'emacs'"
    becomes ``["emacsclient", "-a", "emacs"]``, not the previous broken
    ``["emacsclient", "-a", "'emacs'"]`` from naive str.split.
    """
    for env_var in ("VISUAL", "EDITOR"):
        cmd = os.environ.get(env_var)
        if cmd:
            try:
                parsed = shlex.split(cmd)
            except ValueError:
                # Unbalanced quotes — fall back to naive split rather than
                # silently emit no editor at all.
                parsed = cmd.split()
            if parsed:
                return parsed
    for candidate in ("nano", "vim", "vi"):
        if shutil.which(candidate):
            return [candidate]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# interview — the canonical init question set and resumable runner
# QUESTIONS is the init interview; Interview loops over any question tuple,
# saving answers incrementally so Ctrl-C is safe. extract reuses it.
# ─────────────────────────────────────────────────────────────────────────────

# The full init interview. Order matters — earlier answers prime the user for
# later ones (decisions before risks, risks before open questions, etc.).
QUESTIONS: tuple[Question, ...] = (
    # --- Project identity -------------------------------------------------
    Question(
        key="client",
        prompt="Who is the client?",
        section="Identity",
        help="Company or team name. 'Internal' is a fine answer.",
        required=True,
    ),
    Question(
        key="tagline",
        prompt="One-sentence tagline — what is this thing?",
        section="Identity",
        help="The kind of sentence you'd put under the project name in a README.",
        required=True,
    ),
    Question(
        key="business_goal",
        prompt="What is the business goal? Why is this worth building?",
        section="Identity",
        type="multiline",
        help="A paragraph. The motivating outcome, not the feature list.",
        required=True,
    ),
    Question(
        key="tech_stack",
        prompt="Tech stack (best guess — 'TBD' is OK).",
        section="Identity",
        help='Example: "Python + Supabase + Streamlit". Leave as TBD if Sprint 001 is supposed to decide.',
        default="TBD",
    ),
    # --- Domain -----------------------------------------------------------
    Question(
        key="users",
        prompt="Who uses this? List each user role on its own line.",
        section="Domain",
        type="list",
        help='One role per line. Example:\n  - Operations manager (daily)\n  - Sales lead (weekly review)',
    ),
    Question(
        key="current_process",
        prompt="What does the current (manual) process look like?",
        section="Domain",
        type="multiline",
        help="What happens today — spreadsheets, emails, copy/paste between systems, etc. The thing this project is replacing or augmenting.",
    ),
    Question(
        key="terminology",
        prompt="Client-specific terminology — list terms with definitions (one per line, format: 'term — definition').",
        section="Domain",
        type="list",
        help='Examples:\n  - rebate cycle — quarterly window when payouts are calculated\n  - tier A vendor — pre-approved supplier with auto-pay enabled',
    ),
    Question(
        key="business_rules",
        prompt="Core business rules / invariants (one per line).",
        section="Domain",
        type="list",
        help='Hard truths the system must respect. Example:\n  - Money is stored in integer cents, never floats\n  - A rebate below $5 is never paid out',
    ),
    # --- Decisions --------------------------------------------------------
    Question(
        key="decisions",
        prompt="Decisions already made (one per line, format: 'decision — because').",
        section="Decisions",
        type="list",
        help='Each line: the choice plus the reason. Example:\n  - Supabase over self-hosted Postgres — client already has an account\n  - Ingest via file drop, not API — vendors will not expose an API',
    ),
    Question(
        key="out_of_scope",
        prompt="Explicitly OUT of scope (one per line).",
        section="Decisions",
        type="list",
        help='Things you might be tempted to build but will not. Example:\n  - Mobile app (web only)\n  - Multi-tenant — single-client deployment only',
    ),
    # --- Risks ------------------------------------------------------------
    Question(
        key="risks",
        prompt="Known risks / traps (one per line).",
        section="Risks",
        type="list",
        help='What could derail this? Example:\n  - Source spreadsheets may change column order between quarters\n  - Historical data has inconsistent units (some rows in lbs, some in kg)',
    ),
    Question(
        key="fragile_inputs",
        prompt="Anything fragile about the inputs / data sources?",
        section="Risks",
        type="multiline",
        help="Format drift, missing values, multiple sources of truth, manual upstream steps. A short paragraph is fine.",
    ),
    # --- Open questions ---------------------------------------------------
    Question(
        key="open_questions",
        prompt="What do you still NOT know? (one question per line)",
        section="Questions",
        type="list",
        help='Honest gaps. The Architect will pick these up. Example:\n  - Who owns rebate disputes once flagged?\n  - Is there a maximum rebate per vendor per cycle?',
    ),
    # --- Sprint 001 -------------------------------------------------------
    Question(
        key="sprint1_goal",
        prompt="Sprint 001 (Discovery & Architecture) — what is the goal of THIS sprint?",
        section="Sprint 001",
        type="multiline",
        help="Default for Sprint 001 is producing the planning artifacts and a Sprint 002 build plan. If you have a more specific goal, say so.",
        default="Produce a Builder-ready architecture: confirmed scope, file-level blueprint, and acceptance criteria for Sprint 002.",
    ),
    Question(
        key="sprint1_acceptance",
        prompt="Sprint 001 acceptance criteria (one per line — what must be true to ship this sprint?).",
        section="Sprint 001",
        type="list",
        help='Each criterion should be objectively checkable. Example:\n  - DOMAIN.md describes the rebate cycle in client terminology\n  - blueprint.md lists every file Sprint 002 will create\n  - At least one sample input file is committed to samples/',
    ),
    Question(
        key="sprint1_inspect",
        prompt="Files / sources the Builder should inspect first (one per line — optional).",
        section="Sprint 001",
        type="list",
        help='Example:\n  - samples/rebate-q3.xlsx\n  - references/client-pricing-deck.pdf',
    ),
    # --- State ------------------------------------------------------------
    Question(
        key="state_current",
        prompt="What is the current status, in one or two lines?",
        section="State",
        type="multiline",
        default="Sprint 001 (Discovery & Architecture) — interview complete, planning files populated. Awaiting Architect review.",
    ),
    Question(
        key="state_next",
        prompt="What is the very next action?",
        section="State",
        default="Review planning/ files with the Architect; resolve QUESTIONS.md; produce Sprint 002 requirements.",
    ),
    Question(
        key="state_blockers",
        prompt="Current blockers (one per line, or leave empty).",
        section="State",
        type="list",
    ),
)


@dataclass
class Interview:
    """Stateful interview against an on-disk answer file.

    `project_name` is optional. Callers that want the answer dict to carry a
    `project_name` key (init flow) should pass it; callers that do not
    (extract flow) should leave it empty.
    """

    answers_path: Path
    project_name: str = ""
    answers: dict[str, Any] = field(default_factory=dict)
    resume: bool = False
    editor: bool = False
    questions: tuple[Question, ...] = field(default_factory=lambda: QUESTIONS)

    def load(self) -> None:
        """Load answers from disk if --resume was passed.

        A previous run that was killed mid-save could have left a corrupted
        file. Instead of blowing up with a JSONDecodeError stacktrace, warn
        the operator and start fresh — they'd have to re-answer questions
        either way, and the alternative is unrecoverable from the CLI.
        """
        if not (self.answers_path.exists() and self.resume):
            return
        try:
            self.answers = json.loads(self.answers_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"warning: could not read {self.answers_path}: {e}\n"
                f"  Starting interview from scratch. The corrupt file will be "
                f"overwritten on the first answer.",
                file=sys.stderr,
            )
            self.answers = {}

    def save(self) -> None:
        # Atomic write — see atomic_write_text. Without this, Ctrl-C during
        # save() leaves a truncated file that crashes the next --resume.
        atomic_write_text(
            self.answers_path,
            json.dumps(self.answers, indent=2) + "\n",
        )

    def run(
        self,
        *,
        input_fn: InputFn = input,
        output_fn: OutputFn = print,
    ) -> None:
        self.load()
        if self.project_name:
            self.answers.setdefault("project_name", self.project_name)
        total = len(self.questions)
        current_section: str | None = None
        for i, q in enumerate(self.questions, start=1):
            if q.section != current_section:
                print_section_banner(q.section, output_fn)
                current_section = q.section

            existing = self.answers.get(q.key)
            if self.resume and existing not in (None, "", []):
                output_fn(f"[{i}/{total}] {q.prompt}")
                show_existing(existing, output_fn)
                if not confirm_change(input_fn, output_fn):
                    continue

            value = ask(q, i, total, input_fn, output_fn, editor=self.editor)
            self.answers[q.key] = value
            self.save()

        output_fn("")
        output_fn("Interview complete. Saved to: " + str(self.answers_path))


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

def render_all(target: Path, answers: dict[str, Any]) -> list[Path]:
    """Write every planning/state/sprint file from *answers* into *target*.

    Returns the list of files written.
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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
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
        path.write_text(body, encoding="utf-8")
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


# ─────────────────────────────────────────────────────────────────────────────
# audit — consistency checks for projects and CompanyOS roots
# Principle: no false positives. A check that fires on a healthy project is
# worse than one that misses a real issue — the audit will be ignored. When
# in doubt, emit an INFO finding (advisory), not a WARNING or ERROR.
# ─────────────────────────────────────────────────────────────────────────────


class Severity(Enum):
    """How loudly an audit finding should be reported."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    """One thing the auditor noticed."""

    check: str
    severity: Severity
    message: str
    path: Path | None = None
    line: int | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "check": self.check,
            "severity": self.severity.value,
            "message": self.message,
            "path": str(self.path) if self.path else None,
            "line": self.line,
        }


@dataclass
class AuditReport:
    """The full result of an audit run."""

    project_path: Path
    findings: list[Finding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]


# An audit check is just a function: project path in, findings out.
AuditCheck = Callable[[Path], list[Finding]]

CONFIG_FILE = ".socrates-audit.json"

# Files that should always exist in a populated project. Subset of
# PROJECT_FILES — we exclude README stubs inside src/, tests/, etc. which are
# allowed to be empty and don't carry planning content.
REQUIRED_PLANNING_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "README.md",
    "planning/STATE.md",
    "planning/DECISIONS.md",
    "planning/DOMAIN.md",
    "planning/RISKS.md",
    "planning/QUESTIONS.md",
)

REQUIRED_SPRINT_FILES = (
    "requirements.md",
    "blueprint.md",
    "acceptance.md",
    "handoff-prompt.md",
)

# Words/phrases that hint at lazy acceptance criteria. Conservative list —
# common-but-vague words like "fast" or "good" are NOT here because they
# legitimately appear in client domains. Only flag clear weasels.
WEASEL_WORDS = (
    "TBD",
    "as needed",
    "as appropriate",
    "etc.",
    "and so on",
    "best practices",
    "future-proof",
    "robust enough",
    "where applicable",
)

ALWAYS_ON_RISK_PHRASES = (
    "AI output is not source of truth",
    "ai output must not become the source of truth",
    "ai is not the source of truth",
)

_LAST_UPDATED_RE = re.compile(r"Last updated:\s*(\d{4}-\d{2}-\d{2})")
_SPRINT_NAME_RE = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")
_TERM_RE = re.compile(r"^\s*-\s+([A-Za-z][\w \-/]{1,40}?)\s+[—-]\s+")
_STATE_STALE_DAYS = 30


def check_required_files(project: Path) -> list[Finding]:
    """Every canonical planning file must exist."""
    findings: list[Finding] = []
    for rel in REQUIRED_PLANNING_FILES:
        path = project / rel
        if not path.is_file():
            findings.append(Finding(
                "required-files", Severity.ERROR,
                f"missing required file: {rel}",
                path=path,
            ))
    return findings


def check_sprint_folders(project: Path) -> list[Finding]:
    """Each sprint folder must be named NNN-something and have all 4 required files."""
    findings: list[Finding] = []
    sprints_dir = project / "planning" / "sprints"
    if not sprints_dir.is_dir():
        return findings  # Already flagged by check_required_files if planning/ exists.

    for child in sorted(sprints_dir.iterdir()):
        if not child.is_dir():
            continue
        if not _SPRINT_NAME_RE.match(child.name):
            findings.append(Finding(
                "sprint-folders", Severity.ERROR,
                f"sprint folder '{child.name}' does not match "
                f"NNN-slug convention (e.g. '002-rebate-engine')",
                path=child,
            ))
            continue
        for fname in REQUIRED_SPRINT_FILES:
            if not (child / fname).is_file():
                findings.append(Finding(
                    "sprint-folders", Severity.ERROR,
                    f"sprint '{child.name}' is missing {fname}",
                    path=child / fname,
                ))
    return findings


def check_scaffold_shape(project: Path) -> list[Finding]:
    """The full scaffold tree is *expected* but pruning is legitimate.

    Severity is INFO because operators routinely drop files that aren't relevant
    (e.g. `docs/API.md` on a non-API project). Per-project skip lists live in
    `.socrates-audit.json`:

        {"scaffold_shape": {"ignore": ["docs/API.md", "docs/PERMISSIONS.md"]}}
    """
    ignored = _load_ignore_list(project, "scaffold_shape")
    findings: list[Finding] = []
    for rel in PROJECT_FILES:
        if rel in REQUIRED_PLANNING_FILES:
            continue  # already covered by check_required_files
        if rel in ignored:
            continue
        path = project / rel
        if not path.exists():
            findings.append(Finding(
                "scaffold-shape", Severity.INFO,
                f"scaffold file '{rel}' missing — pruning is allowed, "
                f"but add it to .socrates-audit.json under "
                f"['scaffold_shape']['ignore'] to silence this notice",
                path=path,
            ))
    return findings


def _load_ignore_list(project: Path, section: str) -> set[str]:
    """Load `[section]['ignore']` from `.socrates-audit.json` if present."""
    config_path = project / CONFIG_FILE
    if not config_path.is_file():
        return set()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    sec = data.get(section)
    if not isinstance(sec, dict):
        return set()
    ignore = sec.get("ignore")
    if not isinstance(ignore, list):
        return set()
    return {str(x) for x in ignore}


def check_adapter_routing(project: Path) -> list[Finding]:
    """CLAUDE.md and CODEX.md should reference AGENTS.md (they are routers)."""
    findings: list[Finding] = []
    for adapter in ("CLAUDE.md", "CODEX.md"):
        path = project / adapter
        if not path.is_file():
            continue
        text = path.read_text(errors="replace", encoding="utf-8")
        if "AGENTS.md" not in text:
            findings.append(Finding(
                "adapter-routing", Severity.WARNING,
                f"{adapter} should reference AGENTS.md so the agent "
                f"is routed to the tool-agnostic instructions",
                path=path,
            ))
    return findings


def check_acceptance_weasels(project: Path) -> list[Finding]:
    """Sprint acceptance criteria should be objectively checkable, not weaselly."""
    findings: list[Finding] = []
    sprints_dir = project / "planning" / "sprints"
    if not sprints_dir.is_dir():
        return findings

    for sprint in sorted(sprints_dir.iterdir()):
        if not sprint.is_dir():
            continue
        acc = sprint / "acceptance.md"
        if not acc.is_file():
            continue
        for line_no, line in enumerate(acc.read_text(errors="replace", encoding="utf-8").splitlines(), 1):
            lower = line.lower()
            for weasel in WEASEL_WORDS:
                if weasel.lower() in lower:
                    findings.append(Finding(
                        "acceptance-weasels", Severity.WARNING,
                        f"weasel phrase '{weasel}' in acceptance criterion — "
                        f"tighten to something objectively checkable",
                        path=acc,
                        line=line_no,
                    ))
                    break  # one weasel per line is enough; don't spam
    return findings


def check_state_freshness(project: Path) -> list[Finding]:
    """STATE.md should be edited regularly. Flag if 'Last updated' is > 30 days old."""
    state = project / "planning" / "STATE.md"
    if not state.is_file():
        return []  # Already flagged by check_required_files.
    m = _LAST_UPDATED_RE.search(state.read_text(errors="replace", encoding="utf-8"))
    if not m:
        return [Finding(
            "state-freshness", Severity.INFO,
            "STATE.md does not contain a 'Last updated: YYYY-MM-DD' line",
            path=state,
        )]
    try:
        last = _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return []  # Malformed date; skip rather than crash.
    age = (_dt.date.today() - last).days
    if age > _STATE_STALE_DAYS:
        return [Finding(
            "state-freshness", Severity.WARNING,
            f"STATE.md last updated {age} days ago "
            f"({last.isoformat()}) — update it before continuing",
            path=state,
        )]
    return []


def check_always_on_risks(project: Path) -> list[Finding]:
    """RISKS.md should include the kit's mandated 'AI is not source of truth' reminder."""
    risks = project / "planning" / "RISKS.md"
    if not risks.is_file():
        return []
    lower = risks.read_text(errors="replace", encoding="utf-8").lower()
    if not any(phrase.lower() in lower for phrase in ALWAYS_ON_RISK_PHRASES):
        return [Finding(
            "always-on-risks", Severity.INFO,
            "RISKS.md is missing the always-on reminder that 'AI output is "
            "not source of truth' — recommended by the 120x methodology",
            path=risks,
        )]
    return []


def check_terminology_used(project: Path) -> list[Finding]:
    """Terms defined in DOMAIN.md should appear in at least one other planning file."""
    domain = project / "planning" / "DOMAIN.md"
    if not domain.is_file():
        return []
    terms = _domain_terms(domain.read_text(errors="replace", encoding="utf-8"))
    if not terms:
        return []

    other_text = _other_planning_text(project)
    findings: list[Finding] = []
    for term in terms:
        # Conservative: skip very short terms (single token, <= 3 chars).
        # They risk false-positive matches against unrelated text.
        if len(term) <= 3:
            continue
        # Word-boundary regex with kebab-friendly boundary chars (\w + -).
        # Naive substring search false-positived: a defined term like
        # "tier" matched "tiers", "outlier", "vintner" in any other file
        # and silently suppressed the "term defined but unused" warning.
        pattern = re.compile(
            rf"(?<![\w-]){re.escape(term)}(?![\w-])",
            flags=re.IGNORECASE,
        )
        if not pattern.search(other_text):
            findings.append(Finding(
                "terminology-used", Severity.INFO,
                f"term '{term}' is defined in DOMAIN.md but does not appear "
                f"in any other planning file — is it actually used?",
                path=domain,
            ))
    return findings


def _domain_terms(body: str) -> list[str]:
    in_terminology = False
    terms: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_terminology = "terminology" in stripped.lower()
            continue
        if not in_terminology:
            continue
        m = _TERM_RE.match(line)
        if m:
            terms.append(m.group(1).strip())
    return terms


def _other_planning_text(project: Path) -> str:
    parts: list[str] = []
    candidates = [
        "AGENTS.md", "README.md",
        "planning/STATE.md", "planning/DECISIONS.md",
        "planning/RISKS.md", "planning/QUESTIONS.md",
    ]
    for rel in candidates:
        path = project / rel
        if path.is_file():
            parts.append(path.read_text(errors="replace", encoding="utf-8"))
    # Also include sprint files.
    sprints = project / "planning" / "sprints"
    if sprints.is_dir():
        for sprint in sprints.iterdir():
            if not sprint.is_dir():
                continue
            for f in sprint.glob("*.md"):
                parts.append(f.read_text(errors="replace", encoding="utf-8"))
    return "\n".join(parts)


# Order matters: structural checks first (ERROR-class), then content checks.
PROJECT_CHECKS: tuple[tuple[str, AuditCheck], ...] = (
    ("required-files", check_required_files),
    ("sprint-folders", check_sprint_folders),
    ("scaffold-shape", check_scaffold_shape),
    ("adapter-routing", check_adapter_routing),
    ("acceptance-weasels", check_acceptance_weasels),
    ("state-freshness", check_state_freshness),
    ("always-on-risks", check_always_on_risks),
    ("terminology-used", check_terminology_used),
)


# ── CompanyOS-level checks ───────────────────────────────────────────────────
# These run against a CompanyOS root (the macro layer) rather than a single
# build. They catch consistency issues that *only* exist at the cross-project
# scale: orphaned clients, orphaned patterns, abandoned proposals, etc.

_PROPOSAL_SLUG_RE = re.compile(r"`([a-z][a-z0-9-]*)`")


def check_companyos_structure(project: Path) -> list[Finding]:
    """The CompanyOS root must have its required folders + AGENTS.md."""
    findings: list[Finding] = []
    for rel in ("AGENTS.md", "builds", "clients", "patterns", "pipeline"):
        if not (project / rel).exists():
            findings.append(Finding(
                "companyos-structure", Severity.ERROR,
                f"CompanyOS root is missing '{rel}' — run "
                f"`socrates companyos {project}` to regenerate",
                path=project / rel,
            ))
    return findings


def check_orphan_builds(project: Path) -> list[Finding]:
    """A build with no recorded client, or one whose client folder is missing.

    The heuristic: a build folder's name should match SOME client folder, or
    there should be a `client` reference somewhere in the project's AGENTS.md /
    .socrates-answers.json. If neither, flag.
    """
    builds = project / "builds"
    clients = project / "clients"
    if not builds.is_dir() or not clients.is_dir():
        return []
    client_names = {p.name.lower() for p in clients.iterdir() if p.is_dir()}
    findings: list[Finding] = []
    for build in sorted(builds.iterdir()):
        if not build.is_dir() or not (build / "planning").is_dir():
            continue
        referenced_client = _build_client_reference(build)
        if not referenced_client:
            findings.append(Finding(
                "orphan-builds", Severity.INFO,
                f"build '{build.name}' has no recorded client — "
                f"add 'Client: ...' to AGENTS.md or run `socrates init` again",
                path=build,
            ))
            continue
        if (
            referenced_client.lower() not in client_names
            and referenced_client.lower() != "internal"
        ):
            findings.append(Finding(
                "orphan-builds", Severity.WARNING,
                f"build '{build.name}' references client "
                f"'{referenced_client}' but no clients/{referenced_client}/ "
                f"folder exists",
                path=build,
            ))
    return findings


def check_orphan_pattern_source(project: Path) -> list[Finding]:
    """A pattern that references a `builds/<source>` folder that no longer exists."""
    patterns = project / "patterns"
    builds = project / "builds"
    if not patterns.is_dir() or not builds.is_dir():
        return []
    build_names = {p.name for p in builds.iterdir() if p.is_dir()}
    findings: list[Finding] = []
    for pattern in sorted(patterns.glob("*.md")):
        if pattern.name == "README.md":
            continue
        body = pattern.read_text(errors="replace", encoding="utf-8")
        m = _PATTERN_SOURCE_RE.search(body)
        if not m:
            continue
        source = m.group(1).strip()
        if source not in build_names:
            findings.append(Finding(
                "orphan-pattern-source", Severity.WARNING,
                f"pattern references source project '{source}' which "
                f"no longer exists in builds/ — the provenance is broken",
                path=pattern,
            ))
    return findings


def check_stale_proposals(project: Path) -> list[Finding]:
    """A proposal entry that mentions a slug not present in builds/ may be stale.

    Heuristic: scan pipeline/proposals.md for backtick-wrapped slugs; for each,
    check whether that slug is the name of any directory in builds/. If not,
    emit an INFO advisory — could be an active prospect, could be a
    forgotten one.
    """
    proposals = project / "pipeline" / "proposals.md"
    builds = project / "builds"
    if not proposals.is_file() or not builds.is_dir():
        return []
    build_names = {p.name for p in builds.iterdir() if p.is_dir()}
    body = proposals.read_text(errors="replace", encoding="utf-8")
    findings: list[Finding] = []
    seen: set[str] = set()
    for m in _PROPOSAL_SLUG_RE.finditer(body):
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        # Common false-positive: `python`, `markdown`, etc. — only flag
        # slugs that contain a hyphen (real project names usually do).
        if "-" not in slug:
            continue
        if slug not in build_names:
            findings.append(Finding(
                "stale-proposals", Severity.INFO,
                f"proposals.md mentions `{slug}` but no builds/{slug}/ "
                f"exists — has the engagement started or stalled?",
                path=proposals,
            ))
    return findings


def _build_client_reference(build: Path) -> str | None:
    answers = build / ".socrates-answers.json"
    if answers.is_file():
        try:
            data = json.loads(answers.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                v = data.get("client")
                if isinstance(v, str) and v.strip():
                    return v.strip()
        except (OSError, ValueError):
            pass
    agents = build / "AGENTS.md"
    if agents.is_file():
        text = agents.read_text(errors="replace", encoding="utf-8")
        m = re.search(r"Client:\s*\*\*([^*\n]+)\*\*", text)
        if m:
            return m.group(1).strip()
        m = re.search(r"Client:\s*([^\n]+)", text)
        if m:
            return m.group(1).strip().strip("*").strip()
    return None


COMPANYOS_CHECKS: tuple[tuple[str, AuditCheck], ...] = (
    ("companyos-structure", check_companyos_structure),
    ("orphan-builds", check_orphan_builds),
    ("orphan-pattern-source", check_orphan_pattern_source),
    ("stale-proposals", check_stale_proposals),
)


# ── runner + report formatting ───────────────────────────────────────────────


def run_audit(
    target: Path,
    *,
    checks: tuple[tuple[str, AuditCheck], ...] | None = None,
    companyos: bool = False,
) -> AuditReport:
    """Run every check against *target* and aggregate findings into a report.

    If ``companyos`` is True (or auto-detected via :func:`looks_like_companyos`),
    the macro-level check set is used. Otherwise the per-project checks run.
    """
    if checks is None:
        checks = COMPANYOS_CHECKS if companyos else PROJECT_CHECKS

    report = AuditReport(project_path=target)
    for name, check in checks:
        report.checks_run.append(name)
        report.findings.extend(check(target))
    return report


def looks_like_companyos(path: Path) -> bool:
    """Heuristic: a CompanyOS root has builds/, patterns/, and an AGENTS.md."""
    return (
        (path / "builds").is_dir()
        and (path / "patterns").is_dir()
        and (path / "AGENTS.md").is_file()
    )


_SEV_LABEL = {Severity.ERROR: "ERROR", Severity.WARNING: "WARN ", Severity.INFO: "INFO "}
_SEV_COLOR = {Severity.ERROR: "red", Severity.WARNING: "yellow", Severity.INFO: "cyan"}


def format_report(report: AuditReport, *, as_json: bool = False) -> str:
    if as_json:
        return _format_json(report)
    return _format_text(report)


def _format_json(report: AuditReport) -> str:
    return json.dumps(
        {
            "project_path": str(report.project_path),
            "checks_run": report.checks_run,
            "findings": [f.to_dict() for f in report.findings],
            "counts": {
                "errors": len(report.by_severity(Severity.ERROR)),
                "warnings": len(report.by_severity(Severity.WARNING)),
                "info": len(report.by_severity(Severity.INFO)),
            },
        },
        indent=2,
    )


def _format_text(report: AuditReport) -> str:
    use_color = sys.stdout.isatty()
    lines: list[str] = []
    lines.append(f"socrates audit — {report.project_path}")
    lines.append(f"  ran {len(report.checks_run)} checks: {', '.join(report.checks_run)}")
    lines.append("")

    if not report.findings:
        lines.append("✓ no findings — planning files look internally consistent")
        return "\n".join(lines)

    # Group by severity, ERROR first.
    for sev in (Severity.ERROR, Severity.WARNING, Severity.INFO):
        bucket = report.by_severity(sev)
        if not bucket:
            continue
        label = _color(_SEV_LABEL[sev], _SEV_COLOR[sev], use_color)
        lines.append(f"── {label} ── ({len(bucket)})")
        for f in bucket:
            location = ""
            if f.path:
                try:
                    rel = f.path.relative_to(report.project_path)
                except ValueError:
                    rel = f.path
                location = f"  {rel}"
                if f.line is not None:
                    location += f":{f.line}"
            lines.append(f"  [{f.check}] {f.message}{location}")
        lines.append("")

    counts = (
        f"{len(report.by_severity(Severity.ERROR))} errors, "
        f"{len(report.by_severity(Severity.WARNING))} warnings, "
        f"{len(report.by_severity(Severity.INFO))} info"
    )
    lines.append(counts)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# decide — append a properly dated decision to DECISIONS.md
# Lands in a 'Decisions added after init' section so Sprint 001 history
# stays distinct; the (YYYY-MM-DD) stamp is what `socrates timeline` reads.
# ─────────────────────────────────────────────────────────────────────────────

POST_INIT_HEADING = "## Decisions added after init"
OUT_OF_SCOPE_HEADING = "## Explicitly out of scope"


def record_decision(project: Path, text: str) -> int:
    """Append a dated decision to ``project/planning/DECISIONS.md``.

    Read-modify-write is guarded by an exclusive POSIX file lock and
    the final write is atomic (tempfile + os.replace). Without those:

    - Two concurrent ``socrates decide`` invocations both read the same
      pre-write contents, both compute new bodies, both write. The
      second writer silently clobbers the first — one decision is lost.
      An operator scripting batch decisions or running them from a CI
      hook would have no way to detect the loss after the fact.
    - A SIGINT (Ctrl-C) mid-write to a 5-10 KB DECISIONS.md leaves the
      file truncated and unparseable. ``socrates timeline`` then crashes
      and ``socrates audit`` reports the project as broken.

    DECISIONS.md is the most load-bearing file in a 120x project; both
    failure modes are unacceptable. Going through
    :func:`locked_read_modify_write` addresses both at once.

    Returns a process exit code (0 success, 2 error).
    """
    decisions_path = project / "planning" / "DECISIONS.md"
    if not decisions_path.is_file():
        print(
            f"error: {decisions_path} not found — is {project} a 120x project?",
            file=sys.stderr,
        )
        return 2

    # Collapse internal whitespace runs (including newlines, tabs) to single
    # spaces. A multi-line decision (`socrates decide $'foo\nbar'`) would
    # otherwise produce a bullet whose closing `**` lands on a different
    # line, breaking markdown bold rendering and terminating the list item.
    cleaned = " ".join(text.split())
    if not cleaned:
        print("error: decision text is empty", file=sys.stderr)
        return 2

    today = _dt.date.today().isoformat()
    bullet = f"- **{cleaned} ({today})**"

    locked_read_modify_write(
        decisions_path,
        lambda current: _insert_decision(current, bullet),
    )
    print(f"Appended to {decisions_path}:")
    print(f"  {bullet}")
    return 0


def _insert_decision(body: str, bullet: str) -> str:
    """Insert *bullet* into the right section, creating the section if needed."""
    lines = body.splitlines()
    post_init_idx = _find_heading(lines, POST_INIT_HEADING)
    out_of_scope_idx = _find_heading(lines, OUT_OF_SCOPE_HEADING)

    if post_init_idx is not None:
        # Append to the existing section, just before its next heading (or end).
        insert_at = _next_heading_after(lines, post_init_idx)
        if insert_at is None:
            insert_at = len(lines)
        # Trim trailing blank lines inside the section to keep formatting tight.
        while insert_at > post_init_idx + 1 and lines[insert_at - 1] == "":
            insert_at -= 1
        lines.insert(insert_at, bullet)
        return "\n".join(lines) + ("\n" if body.endswith("\n") else "")

    # Need to create the section. Put it just before "Explicitly out of scope".
    section = ["", POST_INIT_HEADING, "", bullet, ""]
    if out_of_scope_idx is not None:
        for s in reversed(section):
            lines.insert(out_of_scope_idx, s)
        return "\n".join(lines) + ("\n" if body.endswith("\n") else "")

    # No out-of-scope heading either — append at end.
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(section[1:])
    return "\n".join(lines) + "\n"


def _find_heading(lines: list[str], heading: str) -> int | None:
    for i, line in enumerate(lines):
        if line.strip() == heading:
            return i
    return None


def _next_heading_after(lines: list[str], start: int) -> int | None:
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            return i
    return None


# ─────────────────────────────────────────────────────────────────────────────
# journal — append-only daily log
# STATE.md is the rolling snapshot; journal entries are immutable history.
# ─────────────────────────────────────────────────────────────────────────────

# Canonical entry filename: YYYY-MM-DD.md. `_list` and `_show_latest`
# must not pick up unrelated .md files (notes.md, ideas.md, README.md)
# that an operator may have dropped into the journal dir.
_ENTRY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_journal_entry(p: Path) -> bool:
    """True if *p* is a canonical journal entry file (YYYY-MM-DD.md)."""
    return p.suffix == ".md" and bool(_ENTRY_NAME.match(p.stem))


def create_or_open_entry(project: Path, *, show: bool = False, list_all: bool = False) -> int:
    """Create today's journal entry and open $EDITOR, or list/show.

    Returns a process exit code.
    """
    journal_dir = project / "planning" / "journal"
    if not journal_dir.is_dir():
        print(
            f"error: {journal_dir} does not exist — is {project} a 120x project?",
            file=sys.stderr,
        )
        return 2

    if list_all:
        return _list(journal_dir)
    if show:
        return _show_latest(journal_dir)

    today = _dt.date.today().isoformat()
    entry = journal_dir / f"{today}.md"
    is_new = not entry.exists()
    if is_new:
        entry.write_text(_template(today), encoding="utf-8")
        print(f"Created {entry}")

    cmd = editor_command()
    if cmd is None:
        if is_new:
            print("(no $EDITOR / $VISUAL set and no fallback — entry created but not opened)")
            return 0
        print(f"(no $EDITOR set — entry already exists at {entry})")
        return 0
    try:
        subprocess.run([*cmd, str(entry)], check=True)
    except subprocess.CalledProcessError as e:
        print(f"editor exited non-zero ({e.returncode}); entry preserved at {entry}",
              file=sys.stderr)
        return e.returncode
    return 0


def _template(date: str) -> str:
    return f"""# Journal — {date}

## What happened

-

## What surprised me

-

## What did not work

-

## Notes for tomorrow

-
"""


def _list(journal_dir: Path) -> int:
    entries = sorted(p for p in journal_dir.glob("*.md") if _is_journal_entry(p))
    if not entries:
        print("(no journal entries yet — run `socrates journal` to create today's)")
        return 0
    for entry in entries:
        print(entry.name.removesuffix(".md"))
    return 0


def _show_latest(journal_dir: Path) -> int:
    entries = sorted(
        (p for p in journal_dir.glob("*.md") if _is_journal_entry(p)),
        reverse=True,
    )
    if not entries:
        print("(no journal entries yet)")
        return 0
    print(entries[0].read_text(encoding="utf-8"))
    return 0


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
# extract — sprint-close interview that captures a reusable pattern
# The third 120x deliverable (shipped system, preserved blueprint, extracted
# pattern) is the one most often skipped. This makes it cheap.
# ─────────────────────────────────────────────────────────────────────────────

PATTERN_QUESTIONS: tuple[Question, ...] = (
    Question(
        key="pattern_focus",
        prompt=(
            "Look back at this sprint. What is the single most useful thing it "
            "produced that you would re-use on a future project?"
        ),
        section="Pattern",
        type="multiline",
        help=(
            "Free text. Not a feature — a *pattern*. An approach, a piece of code, "
            "a prompt, a piece of scoping language, a workflow."
        ),
        required=True,
    ),
    Question(
        key="pattern_kind",
        prompt="What kind of artifact is it? (one short label)",
        section="Pattern",
        help=(
            "Examples: architecture-pattern, data-ingestion, validation-approach, "
            "prompt-template, scoping-language, pricing-pattern, client-comms, "
            "test-harness, parser, debugging-recipe."
        ),
        required=True,
    ),
    Question(
        key="pattern_slug",
        prompt="Name it as a short kebab-case <verb>-<noun> slug.",
        section="Pattern",
        help=(
            'Examples: validate-parsed-numbers, scope-data-projects, '
            'ingest-vendor-spreadsheets, price-internal-tools.'
        ),
        required=True,
    ),
    Question(
        key="pattern_summary",
        prompt="One sentence — what does it do?",
        section="Pattern",
        required=True,
    ),
    Question(
        key="pattern_when_applies",
        prompt="When does this pattern apply? (the trigger situation)",
        section="Applicability",
        type="multiline",
        help="Be concrete. 'When the client gives you weekly vendor spreadsheets', not 'when there is data'.",
        required=True,
    ),
    Question(
        key="pattern_when_does_not",
        prompt="When does this pattern NOT apply? (where it would break)",
        section="Applicability",
        type="multiline",
        help=(
            "Patterns that don't list their failure modes get cargo-culted. "
            "What kind of project should NOT use this?"
        ),
    ),
    Question(
        key="pattern_body",
        prompt="The pattern itself — paste the code, prompt, template, or sketch.",
        section="Body",
        type="multiline",
        help=(
            "This is the load-bearing field. Be specific enough that you could "
            "drop it into the next project unchanged. --editor mode is recommended."
        ),
        required=True,
    ),
    Question(
        key="pattern_war_story",
        prompt="What about this project taught you this pattern? (the war story)",
        section="Provenance",
        type="multiline",
        help=(
            "The story of how you discovered or earned this pattern. Important "
            "because it grounds the pattern in a real situation, not a theory."
        ),
    ),
    Question(
        key="pattern_confidence",
        prompt="Confidence level — 1 (rough draft) to 5 (battle-tested across many projects).",
        section="Provenance",
        help="A fresh extraction is usually 1 or 2.",
        default="1",
    ),
)


def run_extract(
    project: Path,
    *,
    patterns_dir: Path | None = None,
    resume: bool = False,
    editor: bool = False,
) -> tuple[int, Path | None]:
    """Run the extraction interview and write a pattern candidate.

    Returns (exit_code, path_to_pattern_file).
    """
    target_dir = patterns_dir or _resolve_patterns_dir(project)
    target_dir.mkdir(parents=True, exist_ok=True)

    answers_path = project / ".socrates-extract-answers.json"
    iv = Interview(
        answers_path=answers_path,
        resume=resume,
        editor=editor,
        questions=PATTERN_QUESTIONS,
    )
    try:
        iv.run()
    except KeyboardInterrupt:
        print(
            "\n\nExtraction interrupted. Answers saved. "
            "Re-run with --resume to pick up where you left off.",
        )
        return 130, None

    slug = _sanitize_slug(iv.answers.get("pattern_slug", "untitled"))
    target = target_dir / f"CANDIDATE-{slug}.md"
    target.write_text(render_pattern(iv.answers, project=project), encoding="utf-8")
    print(f"\nPattern candidate written to: {target}")
    print()
    print("Next steps:")
    print(f"  1. Read {target}.")
    print("  2. Tighten the body. Remove anything that does not generalise.")
    print("  3. When the pattern proves itself on a SECOND project, rename")
    print(f"     CANDIDATE-{slug}.md → {slug}.md to promote it.")
    return 0, target


def render_pattern(answers: dict[str, Any], *, project: Path) -> str:
    today = _dt.date.today().isoformat()
    summary = answers.get("pattern_summary") or "_(untitled pattern)_"
    kind = answers.get("pattern_kind") or "_(unclassified)_"
    confidence = answers.get("pattern_confidence") or "1"
    when_applies = answers.get("pattern_when_applies") or "_(not specified)_"
    when_does_not = answers.get("pattern_when_does_not") or "_(not specified)_"
    body = answers.get("pattern_body") or "_(not yet captured)_"
    war_story = answers.get("pattern_war_story") or "_(not captured)_"
    focus = answers.get("pattern_focus") or ""

    return f"""# Pattern: {answers.get("pattern_slug", "untitled")} (CANDIDATE)

> {summary}

| | |
|---|---|
| **Kind** | {kind} |
| **Confidence** | {confidence} / 5 |
| **Extracted** | {today} |
| **Source project** | `{project.name}` |

## When this applies

{when_applies}

## When it does NOT apply

{when_does_not}

## The pattern

{body}

## Why this pattern exists (the war story)

{war_story}

## Original focus (operator's own words at extraction time)

{focus}

---

_This is a CANDIDATE pattern — it has been observed once. Promote to a real pattern (drop the `CANDIDATE-` prefix) only after it has worked on at least one additional project._
"""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_patterns_dir(project: Path) -> Path:
    """Find the patterns/ directory.

    If *project* is inside a CompanyOS layout (i.e. it sits inside a
    `builds/` directory that has a sibling `patterns/`), use that. Otherwise
    fall back to ``project/patterns/``.
    """
    parent = project.parent
    if parent.name == "builds":
        candidate = parent.parent / "patterns"
        if candidate.is_dir() or (parent.parent / "AGENTS.md").exists():
            return candidate
    return project / "patterns"


_NON_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _sanitize_slug(raw: str) -> str:
    slug = raw.strip().lower().replace(" ", "-").replace("_", "-")
    slug = _NON_SLUG_RE.sub("", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"


# ─────────────────────────────────────────────────────────────────────────────
# timeline — chronological feed of journal entries, sprints, decisions
# Answers 'what happened on this project, in order?' without git log.
# ─────────────────────────────────────────────────────────────────────────────

class EventKind(Enum):
    SPRINT = "sprint"
    JOURNAL = "journal"
    DECISION = "decision"


@dataclass(frozen=True)
class TimelineEvent:
    date: _dt.date
    kind: EventKind
    title: str
    detail: str = ""

    @property
    def sort_key(self) -> tuple[str, int, str]:
        # Sort by date ascending, then within a date by kind so that sprints
        # come before journal entries before decisions (sprint header reads
        # naturally above its day's notes).
        return (self.date.isoformat(), self._kind_order(), self.title)

    def _kind_order(self) -> int:
        return {EventKind.SPRINT: 0, EventKind.JOURNAL: 1, EventKind.DECISION: 2}[self.kind]


def build_timeline(project: Path) -> list[TimelineEvent]:
    """Collect all events from a project folder, sorted chronologically."""
    events: list[TimelineEvent] = []
    events.extend(_journal_events(project))
    events.extend(_sprint_events(project))
    events.extend(_decision_events(project))
    return sorted(events, key=lambda e: e.sort_key)


def format_timeline(events: list[TimelineEvent], *, use_color: bool | None = None) -> str:
    if use_color is None:
        use_color = sys.stdout.isatty()
    if not events:
        return "(no timeline events found — has any planning happened yet?)"

    lines: list[str] = []
    current_date: _dt.date | None = None
    for ev in events:
        if ev.date != current_date:
            current_date = ev.date
            lines.append("")
            lines.append(_color(ev.date.isoformat(), "bold", use_color))
        marker = _kind_marker(ev.kind, use_color)
        lines.append(f"  {marker} {ev.title}")
        if ev.detail:
            for line in ev.detail.splitlines():
                lines.append(f"      {_dim(line, use_color)}")
    return "\n".join(lines).lstrip()


# ---------------------------------------------------------------------------
# Event collectors
# ---------------------------------------------------------------------------


def _journal_events(project: Path) -> list[TimelineEvent]:
    journal = project / "planning" / "journal"
    if not journal.is_dir():
        return []
    events: list[TimelineEvent] = []
    for entry in journal.glob("*.md"):
        if entry.name == "README.md":
            continue
        try:
            d = _dt.date.fromisoformat(entry.stem)
        except ValueError:
            continue
        first_line = _first_real_line(entry.read_text(errors="replace", encoding="utf-8"))
        events.append(TimelineEvent(
            date=d,
            kind=EventKind.JOURNAL,
            title="journal entry",
            detail=first_line,
        ))
    return events


def _sprint_events(project: Path) -> list[TimelineEvent]:
    sprints = project / "planning" / "sprints"
    if not sprints.is_dir():
        return []
    events: list[TimelineEvent] = []
    for sprint in sorted(p for p in sprints.iterdir() if p.is_dir()):
        if not re.match(r"^\d{3}-", sprint.name):
            continue
        # Use directory mtime as a proxy for "when did this sprint exist"?
        try:
            mtime = _dt.date.fromtimestamp(sprint.stat().st_mtime)
        except OSError:
            continue
        title = f"sprint {sprint.name}"
        # Pull the requirements goal as detail if present.
        req = sprint / "requirements.md"
        detail = ""
        if req.is_file():
            detail = _extract_goal(req.read_text(errors="replace", encoding="utf-8"))
        events.append(TimelineEvent(
            date=mtime,
            kind=EventKind.SPRINT,
            title=title,
            detail=detail,
        ))
    return events


# The date stamp `socrates decide` and `_decisions_md` both emit is
# anchored at the END of the bullet, immediately before the closing
# `**` and optional trailing whitespace. Anchoring here prevents a
# user-typed date in the decision body (e.g. "Migrate by (2024-12-31)
# (2026-05-20)") from being misread as the recording date — the
# previous unanchored `\((\d{4}-\d{2}-\d{2})\)` regex took the FIRST
# match in the line.
_DATED_DECISION_END = re.compile(r"\((\d{4}-\d{2}-\d{2})\)\*{0,2}\s*$")
# Fallback: any (YYYY-MM-DD) anywhere in the line, in case the line
# does NOT end in the canonical `)**` (older files, hand-edited
# bullets). Used only if the anchored match fails.
_DATED_DECISION_ANY = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")


def _decision_events(project: Path) -> list[TimelineEvent]:
    decisions_file = project / "planning" / "DECISIONS.md"
    if not decisions_file.is_file():
        return []
    events: list[TimelineEvent] = []
    for line in decisions_file.read_text(errors="replace", encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        m = _DATED_DECISION_END.search(stripped) or _DATED_DECISION_ANY.search(stripped)
        if not m:
            continue
        try:
            d = _dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        content = stripped[2:]  # strip "- "
        # Strip ONLY the trailing date stamp (anchored) so dates that appear
        # in the body are preserved in the rendered timeline entry.
        content = _DATED_DECISION_END.sub("", content).strip()
        content = content.strip("*").strip()
        events.append(TimelineEvent(
            date=d,
            kind=EventKind.DECISION,
            title=f"decision: {content}",
        ))
    return events


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _first_real_line(text: str) -> str:
    """First non-empty, non-heading, non-template line of a markdown file."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith("-") and len(s) <= 3:
            continue  # empty bullet from template
        return s[:120]
    return ""


def _extract_goal(text: str) -> str:
    in_goal = False
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_goal:
                break
            in_goal = "goal" in stripped.lower()
            continue
        if in_goal and stripped:
            body.append(stripped)
            if len(body) >= 2:
                break
    return " ".join(body)[:160]


def _kind_marker(kind: EventKind, use_color: bool) -> str:
    label = {EventKind.SPRINT: "[sprint]", EventKind.JOURNAL: "[journal]", EventKind.DECISION: "[decision]"}[kind]
    color = {EventKind.SPRINT: "cyan", EventKind.JOURNAL: "magenta", EventKind.DECISION: "yellow"}[kind]
    return _color(label, color, use_color)


# ─────────────────────────────────────────────────────────────────────────────
# ship — sprint-close pre-flight checklist
# Composition command: audit + journal-today + extract-exists + STATE
# freshness. The four things an operator forgets at sprint close.
# ─────────────────────────────────────────────────────────────────────────────

class CheckResult(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class ShipFinding:
    name: str
    result: CheckResult
    message: str


def preflight(project: Path) -> list[ShipFinding]:
    """Run every pre-flight check. Returns findings in display order."""
    findings: list[ShipFinding] = []

    # 1. Audit must be clean (errors fail; warnings warn).
    findings.append(_audit_check(project))

    # 2. Journal entry for today exists.
    findings.append(_journal_check(project))

    # 3. Extract has been started or completed for this project.
    findings.append(_extract_check(project))

    # 4. STATE.md was touched recently (within 7 days of today).
    findings.append(_state_check(project))

    return findings


def format_preflight(findings: list[ShipFinding], *, use_color: bool | None = None) -> str:
    if use_color is None:
        use_color = sys.stdout.isatty()
    lines = ["socrates ship — sprint-close pre-flight", ""]
    for f in findings:
        marker = _marker(f.result, use_color)
        lines.append(f"  {marker} {f.name}: {f.message}")
    lines.append("")
    failures = [f for f in findings if f.result is CheckResult.FAIL]
    warnings = [f for f in findings if f.result is CheckResult.WARN]
    if failures:
        lines.append(_color(
            f"  ✗ {len(failures)} blocker(s); fix before shipping.",
            "red", use_color,
        ))
    elif warnings:
        lines.append(_color(
            f"  ! {len(warnings)} advisory; sprint is shippable but tighten before next.",
            "yellow", use_color,
        ))
    else:
        lines.append(_color("  ✓ cleared for sprint close.", "green", use_color))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _audit_check(project: Path) -> ShipFinding:
    report = run_audit(project)
    errors = len(report.by_severity(Severity.ERROR))
    warnings = len(report.by_severity(Severity.WARNING))
    if errors:
        return ShipFinding(
            name="audit",
            result=CheckResult.FAIL,
            message=f"{errors} error(s), {warnings} warning(s) — run `socrates audit` for details",
        )
    if warnings:
        return ShipFinding(
            name="audit",
            result=CheckResult.WARN,
            message=f"{warnings} warning(s) — not a blocker but worth tightening",
        )
    return ShipFinding(name="audit", result=CheckResult.PASS, message="planning is clean")


def _journal_check(project: Path) -> ShipFinding:
    today = _dt.date.today()
    entry = project / "planning" / "journal" / f"{today.isoformat()}.md"
    if entry.is_file():
        return ShipFinding(
            name="journal",
            result=CheckResult.PASS,
            message=f"today's entry ({today.isoformat()}) exists",
        )
    return ShipFinding(
        name="journal",
        result=CheckResult.WARN,
        message=(
            "no journal entry for today — run `socrates journal` to log what "
            "happened before declaring the sprint complete"
        ),
    )


def _extract_check(project: Path) -> ShipFinding:
    # Look for both local and CompanyOS-sibling patterns dirs.
    candidate_locations = [project / "patterns"]
    if project.parent.name == "builds":
        candidate_locations.append(project.parent.parent / "patterns")

    found = False
    for loc in candidate_locations:
        if not loc.is_dir():
            continue
        for f in loc.glob("CANDIDATE-*.md"):
            text = f.read_text(errors="replace", encoding="utf-8")
            if f"`{project.name}`" in text:
                found = True
                break
        if found:
            break

    in_progress = (project / ".socrates-extract-answers.json").is_file()

    if found:
        return ShipFinding(
            name="extract",
            result=CheckResult.PASS,
            message="at least one pattern candidate references this project",
        )
    if in_progress:
        return ShipFinding(
            name="extract",
            result=CheckResult.WARN,
            message="extract started but no pattern committed yet — re-run `socrates extract`",
        )
    return ShipFinding(
        name="extract",
        result=CheckResult.WARN,
        message=(
            "no pattern extracted for this sprint — run `socrates extract` "
            "before close (the third 120x deliverable is the one operators "
            "skip; ship blocks the habit from forming)"
        ),
    )


def _state_check(project: Path) -> ShipFinding:
    state = project / "planning" / "STATE.md"
    if not state.is_file():
        return ShipFinding(
            name="state",
            result=CheckResult.FAIL,
            message="planning/STATE.md missing",
        )
    m = _LAST_UPDATED_RE.search(state.read_text(errors="replace", encoding="utf-8"))
    if not m:
        return ShipFinding(
            name="state",
            result=CheckResult.WARN,
            message="STATE.md has no 'Last updated' line — add one",
        )
    try:
        last = _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return ShipFinding(
            name="state",
            result=CheckResult.WARN,
            message="STATE.md 'Last updated' date is unparseable",
        )
    age = (_dt.date.today() - last).days
    if age > 7:
        return ShipFinding(
            name="state",
            result=CheckResult.WARN,
            message=f"STATE.md last touched {age} days ago — refresh before close",
        )
    return ShipFinding(
        name="state",
        result=CheckResult.PASS,
        message=f"STATE.md updated {age} day(s) ago",
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _marker(result: CheckResult, use_color: bool) -> str:
    glyph = {CheckResult.PASS: "✓", CheckResult.WARN: "!", CheckResult.FAIL: "✗"}[result]
    color = {CheckResult.PASS: "green", CheckResult.WARN: "yellow", CheckResult.FAIL: "red"}[result]
    return _color(glyph, color, use_color)


# ─────────────────────────────────────────────────────────────────────────────
# status — CompanyOS-level health dashboard
# One line per builds/<project>/: sprint, audit counts, STATE/journal age,
# extract done. The first thing the operator reads each morning.
# ─────────────────────────────────────────────────────────────────────────────

STALE_STATE_DAYS = 14
STALE_JOURNAL_DAYS = 7


@dataclass
class ProjectStatus:
    name: str
    tagline: str
    active_sprint: str
    audit_errors: int
    audit_warnings: int
    state_age_days: int | None
    journal_age_days: int | None
    has_extract: bool


def companyos_status(root: Path) -> list[ProjectStatus]:
    """Return a status summary for every project under ``root/builds/``."""
    builds = root / "builds"
    if not builds.is_dir():
        return []
    results: list[ProjectStatus] = []
    for project in sorted(p for p in builds.iterdir() if p.is_dir()):
        # Skip non-project folders (e.g. README.md sentinel files).
        if not (project / "planning").is_dir():
            continue
        results.append(_summarize(project))
    return results


def format_status(rows: list[ProjectStatus], *, use_color: bool | None = None) -> str:
    if use_color is None:
        use_color = sys.stdout.isatty()
    if not rows:
        return "(no project folders found under builds/)"

    name_w = max(8, max(len(r.name) for r in rows))
    sprint_w = max(10, max(len(r.active_sprint) for r in rows))

    lines: list[str] = []
    lines.append(
        f"{'project':<{name_w}}  {'sprint':<{sprint_w}}  "
        f"{'audit':<8}  {'STATE':<10}  {'journal':<10}  extract"
    )
    lines.append("─" * (name_w + sprint_w + 8 + 10 + 10 + 10 + 12))

    for r in rows:
        audit_chunk = _color(
            f"E{r.audit_errors}W{r.audit_warnings}",
            "red" if r.audit_errors else "yellow" if r.audit_warnings else "green",
            use_color,
        )
        state_chunk = _color(
            _age_label(r.state_age_days),
            _age_color(r.state_age_days, STALE_STATE_DAYS),
            use_color,
        )
        journal_chunk = _color(
            _age_label(r.journal_age_days),
            _age_color(r.journal_age_days, STALE_JOURNAL_DAYS),
            use_color,
        )
        extract_chunk = _color(
            "✓" if r.has_extract else "—",
            "green" if r.has_extract else "yellow",
            use_color,
        )
        lines.append(
            f"{r.name:<{name_w}}  {r.active_sprint:<{sprint_w}}  "
            f"{audit_chunk:<8}  {state_chunk:<10}  {journal_chunk:<10}  {extract_chunk}"
        )
        if r.tagline:
            lines.append(f"{'':<{name_w}}    {_dim(r.tagline, use_color)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _summarize(project: Path) -> ProjectStatus:
    name = project.name
    tagline = _project_tagline(project)
    active = _extract_active_sprint(project)

    audit_errors = 0
    audit_warnings = 0
    try:
        report = run_audit(project)
        audit_errors = len(report.by_severity(Severity.ERROR))
        audit_warnings = len(report.by_severity(Severity.WARNING))
    except OSError:
        # Audit choked on a permission or read error — treat as 0 + 0; the
        # operator can rerun `socrates audit <project>` for the real reason.
        pass

    state_age = _state_age_days(project)
    journal_age = _latest_journal_age_days(project)
    has_extract = _has_extract(project)

    return ProjectStatus(
        name=name,
        tagline=tagline,
        active_sprint=active,
        audit_errors=audit_errors,
        audit_warnings=audit_warnings,
        state_age_days=state_age,
        journal_age_days=journal_age,
        has_extract=has_extract,
    )


def _project_tagline(project: Path) -> str:
    answers_path = project / ".socrates-answers.json"
    if answers_path.is_file():
        try:
            data = json.loads(answers_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                t = data.get("tagline")
                if isinstance(t, str):
                    return t
        except (OSError, ValueError):
            pass
    agents = project / "AGENTS.md"
    if agents.is_file():
        m = re.search(r"\*\*[^*]+\*\*\s+—\s+(.+)", agents.read_text(errors="replace", encoding="utf-8"))
        if m:
            return m.group(1).strip()
    return ""


def _extract_active_sprint(project: Path) -> str:
    sprints = project / "planning" / "sprints"
    if not sprints.is_dir():
        return "—"
    candidates = sorted(p.name for p in sprints.iterdir() if p.is_dir())
    if not candidates:
        return "—"
    # Heuristic: highest-numbered sprint folder. Strip the slug — show NNN-name
    # but truncate aggressively for table layout.
    name = candidates[-1]
    if len(name) > 18:
        name = name[:17] + "…"
    return name


def _state_age_days(project: Path) -> int | None:
    state = project / "planning" / "STATE.md"
    if not state.is_file():
        return None
    m = _LAST_UPDATED_RE.search(state.read_text(errors="replace", encoding="utf-8"))
    if not m:
        return None
    try:
        d = _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return (_dt.date.today() - d).days


def _latest_journal_age_days(project: Path) -> int | None:
    journal = project / "planning" / "journal"
    if not journal.is_dir():
        return None
    entries = [p for p in journal.glob("*.md") if p.name != "README.md"]
    if not entries:
        return None
    latest_name = max(p.stem for p in entries)
    try:
        d = _dt.date.fromisoformat(latest_name)
    except ValueError:
        return None
    return (_dt.date.today() - d).days


def _has_extract(project: Path) -> bool:
    """A project has been "extracted" if any pattern candidate references it.

    Two prior bugs fixed here:
    - Each pattern file was read TWICE (once per substring check). On a
      CompanyOS with N projects and M patterns, status() became O(N*M)
      file reads. Read once, check both patterns against the same text.
    - The fallback ``f"\\`{project.name}\\`" in text`` matched any backtick
      mention of the project — a war story in pattern P that says
      ``see \\`other-project\\` for context`` would falsely mark
      other-project as having an extract. Drop the loose fallback; only
      the explicit ``Source project | \\`name\\``` line is authoritative.
    """
    # 1) Local patterns/ dir with CANDIDATE-*.md.
    local = project / "patterns"
    if local.is_dir() and any(local.glob("CANDIDATE-*.md")):
        return True
    # 2) Sibling CompanyOS patterns/ dir.
    parent = project.parent
    if parent.name == "builds":
        sibling = parent.parent / "patterns"
        if sibling.is_dir():
            source_marker = f"Source project** | `{project.name}`"
            # Tolerate both pattern emitters' formats (markdown table cell
            # may or may not have the ** around the label depending on
            # render version).
            source_marker_alt = f"Source project | `{project.name}`"
            for f in sibling.glob("CANDIDATE-*.md"):
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if source_marker in text or source_marker_alt in text:
                    return True
    # 3) Or has an in-progress extract answers file.
    return (project / ".socrates-extract-answers.json").is_file()


def _age_label(days: int | None) -> str:
    if days is None:
        return "—"
    if days == 0:
        return "today"
    if days == 1:
        return "1d"
    return f"{days}d"


def _age_color(days: int | None, threshold: int) -> str:
    if days is None:
        return "dim"
    if days > threshold * 2:
        return "red"
    if days > threshold:
        return "yellow"
    return "green"


# ─────────────────────────────────────────────────────────────────────────────
# patterns — review the patterns/ folder for drift
# Stale candidates (>90d), orphaned sources, never-reused slugs. The
# rgrep across builds is cached in patterns/.usage-cache.json with
# per-project mtime invalidation (schema documented at _compute_usage_map).
# ─────────────────────────────────────────────────────────────────────────────

STALE_CANDIDATE_DAYS = 90
USAGE_CACHE_FILENAME = ".usage-cache.json"
USAGE_CACHE_VERSION = 2


class FindingKind(Enum):
    STALE = "stale-candidate"
    ORPHAN = "orphan-source"
    UNUSED = "unused"


@dataclass(frozen=True)
class PatternFinding:
    kind: FindingKind
    path: Path
    message: str


@dataclass
class PatternReport:
    patterns_dir: Path
    findings: list[PatternFinding]
    candidates_total: int
    promoted_total: int


def review_patterns(companyos_root: Path, *, use_cache: bool = True) -> PatternReport:
    """Inspect *companyos_root*/patterns/ and report drift.

    ``use_cache=True`` (the default) reads ``patterns/.usage-cache.json`` and
    reuses any **per-project segment** whose tracked mtime hasn't changed.
    Adding/removing a pattern invalidates the slug-set check and forces a
    re-grep per project; changing a file in project P only invalidates P.
    Pass ``use_cache=False`` to drop the cache entirely for one run.
    """
    patterns_dir = companyos_root / "patterns"
    findings: list[PatternFinding] = []
    candidates = 0
    promoted = 0

    if not patterns_dir.is_dir():
        return PatternReport(patterns_dir, findings, 0, 0)

    builds_dir = companyos_root / "builds"
    if builds_dir.is_dir():
        build_names: set[str] | None = {p.name for p in builds_dir.iterdir() if p.is_dir()}
    else:
        build_names = None

    pattern_files = sorted(p for p in patterns_dir.glob("*.md") if p.name != "README.md")
    cache = _load_usage_cache(patterns_dir) if use_cache else None
    usage_map = _compute_usage_map(pattern_files, builds_dir, build_names, cache=cache)

    today = _dt.date.today()
    for pattern in pattern_files:
        is_candidate = pattern.name.startswith("CANDIDATE-")
        if is_candidate:
            candidates += 1
        else:
            promoted += 1
        body = pattern.read_text(errors="replace", encoding="utf-8")
        source = _extract_source_project(body)
        extracted = _extract_extracted_date(body)

        # Stale candidate check.
        if is_candidate and extracted is not None:
            age = (today - extracted).days
            if age > STALE_CANDIDATE_DAYS:
                findings.append(PatternFinding(
                    kind=FindingKind.STALE,
                    path=pattern,
                    message=(
                        f"candidate is {age} days old (threshold {STALE_CANDIDATE_DAYS}d) — "
                        f"promote it or delete it"
                    ),
                ))

        # Orphan source check.
        if source and build_names is not None and source not in build_names:
            findings.append(PatternFinding(
                kind=FindingKind.ORPHAN,
                path=pattern,
                message=(
                    f"source project '{source}' no longer exists in builds/ — "
                    f"the pattern's provenance is broken"
                ),
            ))

        # Unused check via the (possibly cached) usage_map.
        if build_names and len(build_names - {source} if source else build_names) > 0:
            slug = _pattern_slug(pattern.name)
            if slug:
                used_in = usage_map.get(slug, [])
                # Exclude the source project from the use list.
                used_outside = [p for p in used_in if p != source]
                if not used_outside:
                    findings.append(PatternFinding(
                        kind=FindingKind.UNUSED,
                        path=pattern,
                        message=(
                            f"slug '{slug}' is not referenced in any project outside "
                            f"its source — pattern has not yet compounded"
                        ),
                    ))
    return PatternReport(
        patterns_dir=patterns_dir,
        findings=findings,
        candidates_total=candidates,
        promoted_total=promoted,
    )


# ---------------------------------------------------------------------------
# Usage cache (per-project segments, v2)
#
# Schema:
#   {
#     "version": 2,
#     "computed_at": "ISO-8601",
#     "slug_set": ["validate-numbers", "ingest-pipeline", ...],
#     "projects": {
#       "alpha": {"mtime": 1620000000.0, "matched_slugs": ["validate-numbers"]},
#       "beta":  {"mtime": 1620100000.0, "matched_slugs": []}
#     }
#   }
#
# Per-project segment reuse: if a project's tracked mtime equals the live max
# mtime of its *.md files, that project's matched_slugs are reused verbatim.
# Otherwise we re-grep that project against the current slug_set. Adding or
# removing a pattern changes the slug_set, which forces every per-project
# segment to recompute (cheaper than re-grepping nothing would be wrong; the
# alternative — diffing slugs — is deferred until anyone hits the limit).
# ---------------------------------------------------------------------------


def _compute_usage_map(
    pattern_files: list[Path],
    builds_dir: Path,
    build_names: set[str] | None,
    *,
    cache: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Return slug -> [project, ...]; updates and persists the cache as a side effect."""
    if not build_names:
        return {}

    current_slugs = sorted({s for p in pattern_files if (s := _pattern_slug(p.name))})
    cached_slug_set = cache.get("slug_set") if cache else None
    slug_set_unchanged = cached_slug_set == current_slugs

    cached_projects = cache.get("projects", {}) if cache else {}

    new_projects: dict[str, dict[str, Any]] = {}
    for name in sorted(build_names):
        project_dir = builds_dir / name
        live_mtime = _project_mtime(project_dir)
        cached_proj = cached_projects.get(name)
        if (
            slug_set_unchanged
            and cached_proj is not None
            and _approx_eq(cached_proj.get("mtime"), live_mtime)
            and isinstance(cached_proj.get("matched_slugs"), list)
        ):
            matched = [str(s) for s in cached_proj["matched_slugs"] if isinstance(s, str)]
        else:
            matched = [s for s in current_slugs if _slug_in_project(s, project_dir)]
        new_projects[name] = {"mtime": live_mtime, "matched_slugs": matched}

    # Persist the refreshed cache.
    payload = {
        "version": USAGE_CACHE_VERSION,
        "computed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "slug_set": current_slugs,
        "projects": new_projects,
    }
    _save_usage_cache(pattern_files[0].parent if pattern_files else builds_dir.parent / "patterns", payload)

    # Invert: slug -> list of projects mentioning it.
    inverted: dict[str, list[str]] = {slug: [] for slug in current_slugs}
    for proj_name, info in new_projects.items():
        for slug in info["matched_slugs"]:
            if slug in inverted:
                inverted[slug].append(proj_name)
    return inverted


def _slug_in_project(slug: str, project_dir: Path) -> bool:
    """True if *slug* appears as a complete token in any .md file under
    *project_dir*.

    Naive substring match (the previous implementation) false-positived on
    short slugs: ``auth`` matched ``author`` / ``authentic`` / ``authority``,
    ``api`` matched ``apiary`` / ``rapidly``. The "unused candidate" report
    silently hid genuine unused patterns whenever such a short slug
    happened to be substring of a real word in any project's planning
    files.

    Word-boundary regex with custom boundary chars (``\\w`` plus ``-``)
    handles kebab-case slugs correctly: ``validate-numbers`` won't match
    inside ``validate-numbers-attempt`` (longer kebab identifier), and
    ``auth`` won't match inside ``author``.
    """
    needle = slug.lower()
    # (?<![\w-]) — not preceded by a word char or dash
    # (?![\w-])  — not followed by a word char or dash
    # re.escape protects against any regex metacharacters in slug names.
    pattern = re.compile(
        rf"(?<![\w-]){re.escape(needle)}(?![\w-])",
        flags=re.IGNORECASE,
    )
    for f in project_dir.rglob("*.md"):
        try:
            text = f.read_text(errors="replace", encoding="utf-8")
        except OSError:
            continue
        if pattern.search(text):
            return True
    return False


def _project_mtime(project_dir: Path) -> float:
    max_mtime = 0.0
    for f in project_dir.rglob("*.md"):
        try:
            max_mtime = max(max_mtime, f.stat().st_mtime)
        except OSError:
            continue
    return max_mtime


def _approx_eq(a: object, b: float) -> bool:
    """mtime equality with a tiny tolerance — JSON round-trip can shave fractions."""
    if not isinstance(a, (int, float)):
        return False
    return abs(float(a) - b) < 0.001


def _load_usage_cache(patterns_dir: Path) -> dict[str, Any] | None:
    cache_path = patterns_dir / USAGE_CACHE_FILENAME
    if not cache_path.is_file():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != USAGE_CACHE_VERSION:
        return None
    if not isinstance(data.get("projects"), dict):
        return None
    return data


def _save_usage_cache(patterns_dir: Path, payload: dict[str, Any]) -> None:
    """Persist the usage cache atomically.

    `socrates patterns review` on a CompanyOS with many projects can take
    seconds. A SIGINT mid-write would leave a truncated/invalid cache
    file, which would then crash the next run inside json.loads. Use a
    same-directory tempfile + os.replace for atomicity (same pattern as
    interview.py's atomic save) so the cache is either fully old or
    fully new — never half-written.
    """
    if not patterns_dir.is_dir():
        return
    target = patterns_dir / USAGE_CACHE_FILENAME
    tmp = target.with_name(target.name + ".tmp")
    try:
        with contextlib.suppress(OSError):
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def format_pattern_report(report: PatternReport, *, use_color: bool | None = None) -> str:
    if use_color is None:
        use_color = sys.stdout.isatty()
    lines: list[str] = []
    lines.append(f"socrates patterns review — {report.patterns_dir}")
    lines.append(
        f"  {report.candidates_total} candidate(s), "
        f"{report.promoted_total} promoted, "
        f"{len(report.findings)} finding(s)"
    )
    lines.append("")
    if not report.findings:
        lines.append("✓ no findings — patterns layer looks healthy")
        return "\n".join(lines)

    by_kind: dict[FindingKind, list[PatternFinding]] = {k: [] for k in FindingKind}
    for f in report.findings:
        by_kind[f.kind].append(f)

    for kind in FindingKind:
        bucket = by_kind[kind]
        if not bucket:
            continue
        lines.append(f"── {kind.value} ── ({len(bucket)})")
        for f in bucket:
            try:
                rel = f.path.relative_to(report.patterns_dir.parent)
            except ValueError:
                rel = f.path
            lines.append(f"  {rel}: {f.message}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_PATTERN_SOURCE_RE = re.compile(r"\*\*Source project\*\*\s*\|\s*`([^`]+)`")
_PATTERN_EXTRACTED_RE = re.compile(r"\*\*Extracted\*\*\s*\|\s*(\d{4})-(\d{2})-(\d{2})")


def _extract_source_project(body: str) -> str | None:
    m = _PATTERN_SOURCE_RE.search(body)
    return m.group(1) if m else None


def _extract_extracted_date(body: str) -> _dt.date | None:
    m = _PATTERN_EXTRACTED_RE.search(body)
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _pattern_slug(filename: str) -> str:
    name = filename.removeprefix("CANDIDATE-").removesuffix(".md")
    return name.strip()


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


# ─────────────────────────────────────────────────────────────────────────────
# cli — argparse wiring for the `socrates` command
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="socrates",
        description=(
            "120xSocrates — tooling on top of the 120x Operators Kit. "
            "Scaffold + interview a new project, or audit an existing one."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser(
        "init",
        help="Scaffold a project and run the Socratic interview.",
        description="Create the 120x folder tree and interview the operator to populate it.",
    )
    init.add_argument(
        "project",
        help="Project slug (e.g. 'quarterly-rebates'). Becomes a folder under --base.",
    )
    init.add_argument(
        "--base", type=Path, default=Path.cwd(),
        help="Parent directory in which to create the project folder. Default: cwd.",
    )
    init.add_argument(
        "--no-scaffold", action="store_true",
        help="Skip the scaffold step. Use when the project folder already exists.",
    )
    init.add_argument(
        "--resume", action="store_true",
        help="Resume a partially-completed interview from .socrates-answers.json.",
    )
    init.add_argument(
        "--no-render", action="store_true",
        help="Save answers but do NOT write the .md files yet.",
    )
    init.add_argument(
        "--editor", action="store_true",
        help="For multi-line questions, open $EDITOR instead of prompting line-by-line.",
    )

    timeline = sub.add_parser(
        "timeline",
        help="Chronological view of journal entries, sprints, and dated decisions.",
        description=(
            "Build a single chronological feed from planning/journal/, "
            "planning/sprints/, and dated entries in DECISIONS.md. Answers "
            "'what happened on this project, in order?' without scanning git log."
        ),
    )
    timeline.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: cwd.",
    )

    ship = sub.add_parser(
        "ship",
        help="Sprint-close pre-flight: audit + journal + extract + state freshness.",
        description=(
            "Run the four pre-flight checks before declaring a sprint complete. "
            "Composition command — chains existing logic into one ritual. "
            "Exits non-zero if any check fails."
        ),
    )
    ship.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: cwd.",
    )

    pack = sub.add_parser(
        "pack",
        help="Assemble an Architect input bundle (single markdown file).",
        description=(
            "Concatenate AGENTS / STATE / DOMAIN / DECISIONS / RISKS / QUESTIONS "
            "and the active sprint's files into one paste-able markdown bundle "
            "for the Architect (browser chat) session."
        ),
    )
    pack.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: cwd.",
    )
    pack.add_argument(
        "--sprint", type=str, default=None,
        help="Include this sprint folder instead of auto-detecting the highest-numbered one.",
    )
    pack.add_argument(
        "--stdout", action="store_true",
        help="Print to stdout instead of writing .socrates-architect-pack.md.",
    )
    pack.add_argument(
        "--include-philosophy", action="store_true",
        help=(
            "Prepend a short, original 120x stance written by socrates. "
            "Useful when the Architect chat is fresh and needs the "
            "Architect/Builder split explained inline."
        ),
    )
    pack.add_argument(
        "--kit-path", type=Path, default=None,
        help=(
            "Path to a local 120x Operators Kit checkout. Its three load-bearing "
            "files (philosophy, scaffold-instructions, quickstart) will be "
            "embedded in the pack. Falls back to the $SOCRATES_KIT_PATH env var."
        ),
    )
    pack.add_argument(
        "--format", choices=("md", "html", "xml"), default="md",
        dest="pack_format",
        help=(
            "Output format. `md` (default) is plain markdown — the historical "
            "behavior. `xml` wraps markdown bodies in <section> tags, matching "
            "Anthropic's prompt-engineering recommendation for structural "
            "delimitation. `html` produces full HTML (requires the optional "
            "`markdown` package: `pip install socrates120x[html]`)."
        ),
    )

    patterns = sub.add_parser(
        "patterns",
        help="Inspect the patterns/ folder for staleness, orphans, and unused candidates.",
        description=(
            "Operates at the CompanyOS root. Scans patterns/ and reports "
            "stale candidates (>90d old), patterns whose source project no "
            "longer exists, and patterns whose slug is not referenced from "
            "any project outside their source — i.e. patterns that have not "
            "yet compounded."
        ),
    )
    patterns_sub = patterns.add_subparsers(dest="patterns_command", required=True)
    patterns_review = patterns_sub.add_parser(
        "review",
        help="Audit the patterns/ folder.",
    )
    patterns_review.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="CompanyOS root. Default: cwd.",
    )
    patterns_review.add_argument(
        "--no-cache", action="store_true",
        help=(
            "Force a full rescan instead of using patterns/.usage-cache.json. "
            "The cache is still written; this just ignores it for one run."
        ),
    )

    status = sub.add_parser(
        "status",
        help="One-screen health dashboard for every project in a CompanyOS.",
        description=(
            "Scan every builds/<project>/ under a CompanyOS root and print a "
            "one-line health summary per project: active sprint, audit error "
            "count, days since STATE / journal updates, whether extract has "
            "been run. Designed as the first thing the operator reads each day."
        ),
    )
    status.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="CompanyOS root. Default: cwd.",
    )

    onboard = sub.add_parser(
        "onboard",
        help="Synthesize a 60-second WELCOME.md from the existing planning files.",
        description=(
            "Read STATE / DECISIONS / RISKS / QUESTIONS and write a WELCOME.md "
            "in the project root. Pure synthesis — no interview. Designed for "
            "new humans or agents who need a one-minute briefing."
        ),
    )
    onboard.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: current working directory.",
    )
    onboard.add_argument(
        "--stdout", action="store_true",
        help="Print the synthesized briefing to stdout instead of writing WELCOME.md.",
    )

    extract = sub.add_parser(
        "extract",
        help="Sprint-close interview: capture a reusable pattern from this project.",
        description=(
            "Walk through 9 questions to extract one reusable pattern from the "
            "sprint that just shipped, then write it as patterns/CANDIDATE-<slug>.md. "
            "Run this at the end of every sprint or project — the third deliverable "
            "the 120x methodology promises is the one most often skipped."
        ),
    )
    extract.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: current working directory.",
    )
    extract.add_argument(
        "--patterns-dir", type=Path, default=None,
        help=(
            "Where to write the pattern file. Default: auto-detect (sibling "
            "patterns/ if inside a CompanyOS, else project-local patterns/)."
        ),
    )
    extract.add_argument(
        "--resume", action="store_true",
        help="Resume a partial extraction from .socrates-extract-answers.json.",
    )
    extract.add_argument(
        "--editor", action="store_true",
        help="Use $EDITOR for multi-line answers (recommended for the pattern body).",
    )

    companyos = sub.add_parser(
        "companyos",
        help="Scaffold a CompanyOS macro layer (the wrapper around per-project builds).",
        description=(
            "Create the 120x macro layer at the given path: clients/, builds/, "
            "patterns/, pipeline/, content/, reference/, daily/, templates/. "
            "This is the wrapper around per-project builds — the 'factory', not the 'house'."
        ),
    )
    companyos.add_argument(
        "path", type=Path,
        help="Directory to scaffold the CompanyOS into (created if missing).",
    )

    decide = sub.add_parser(
        "decide",
        help="Append a dated decision to planning/DECISIONS.md.",
        description=(
            "Append one decision to the project's DECISIONS.md, stamped with "
            "today's date in the `(YYYY-MM-DD)` format that `socrates timeline` "
            "reads. The decision lands in a 'Decisions added after init' "
            "section so the Sprint 001 history stays distinct."
        ),
    )
    decide.add_argument(
        "text",
        help='The decision body, e.g. "DuckDB over Postgres — local file is fine".',
    )
    decide.add_argument(
        "--path", type=Path, default=Path.cwd(),
        help="Project folder. Default: cwd.",
    )

    journal = sub.add_parser(
        "journal",
        help="Create or open today's planning/journal/YYYY-MM-DD.md entry.",
        description=(
            "Open today's journal entry in $EDITOR. Creates the file with a "
            "short template if it does not yet exist. Use --show to print the "
            "latest entry, --list to list every entry."
        ),
    )
    journal.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: current working directory.",
    )
    journal.add_argument(
        "--show", action="store_true",
        help="Print the latest journal entry to stdout instead of editing.",
    )
    journal.add_argument(
        "--list", action="store_true", dest="list_all",
        help="List all journal entries, oldest first.",
    )

    audit = sub.add_parser(
        "audit",
        help="Verify the planning files of a 120x project for internal consistency.",
        description=(
            "Scan a 120x project for missing files, broken sprint folders, weasel "
            "words in acceptance criteria, stale STATE, etc. Exits non-zero on errors."
        ),
    )
    audit.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder to audit. Default: current working directory.",
    )
    audit.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as errors when computing the exit code.",
    )
    audit.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    audit_mode = audit.add_mutually_exclusive_group()
    audit_mode.add_argument(
        "--project", action="store_true",
        help="Force per-project audit (default unless the target looks like a CompanyOS root).",
    )
    audit_mode.add_argument(
        "--companyos", action="store_true",
        help="Force CompanyOS-level audit (orphan builds/clients/patterns, stale proposals).",
    )

    args = parser.parse_args(argv)
    commands: dict[str, Callable[[argparse.Namespace], int]] = {
        "init": _cmd_init, "audit": _cmd_audit, "journal": _cmd_journal,
        "companyos": _cmd_companyos, "extract": _cmd_extract,
        "onboard": _cmd_onboard, "status": _cmd_status, "patterns": _cmd_patterns,
        "timeline": _cmd_timeline, "ship": _cmd_ship, "pack": _cmd_pack,
        "decide": _cmd_decide,
    }
    return commands[args.command](args)


# ---------------------------------------------------------------------------
# `init` subcommand
# ---------------------------------------------------------------------------


def _validate_slug(slug: str, *, kind: str = "project") -> str | None:
    """Return an error message if *slug* would escape its parent directory or
    is otherwise unsafe to use as a single path component; ``None`` if OK.

    Reject:
      - empty / whitespace-only slugs (would resolve to the base dir)
      - slugs containing a path separator (``/`` or ``\\``) — would nest or
        traverse outside the intended parent
      - slugs equal to ``.`` or ``..`` or that contain a ``..`` segment
      - absolute paths (Path("/x") / "/etc" returns "/etc" — the slug wins)
      - slugs containing NUL bytes (defensive against API misuse)

    Allowed: alphanumeric, dash, underscore, dot (for slugs like ``v0.8.0``
    or ``.hidden`` if the operator really wants those).
    """
    if not slug or not slug.strip():
        return f"{kind} slug cannot be empty."
    if "\x00" in slug:
        return f"{kind} slug cannot contain NUL bytes."
    if "/" in slug or "\\" in slug:
        return (
            f"{kind} slug must be a single path component "
            f"(no '/' or '\\\\'); got {slug!r}."
        )
    # PurePath of an absolute slug yields an absolute path, which would
    # discard the base when joined with /. Reject explicitly.
    if Path(slug).is_absolute():
        return (
            f"{kind} slug must be relative, not absolute; got {slug!r}. "
            f"Use --base to choose a different parent directory."
        )
    parts = Path(slug).parts
    if parts and (parts[0] == ".." or any(p == ".." for p in parts)):
        return (
            f"{kind} slug cannot contain '..' segments; got {slug!r}. "
            f"Use --base to choose a different parent directory."
        )
    if slug in {".", ".."}:
        return f"{kind} slug cannot be {slug!r}."
    return None


def _cmd_init(args: argparse.Namespace) -> int:
    slug_err = _validate_slug(args.project, kind="project")
    if slug_err:
        print(f"error: {slug_err}", file=sys.stderr)
        return 2
    target: Path = args.base.expanduser().resolve() / args.project

    if not args.no_scaffold:
        if target.exists():
            print(
                f"error: {target} already exists. "
                f"Pass --no-scaffold to populate an existing folder, "
                f"or choose a different project slug.",
                file=sys.stderr,
            )
            return 2
        print(f"Scaffolding 120x structure at: {target}")
        scaffold(target)
    else:
        if not target.exists():
            print(
                f"error: {target} does not exist and --no-scaffold was passed.",
                file=sys.stderr,
            )
            return 2
        print(f"Using existing folder: {target}")

    if not is_interactive():
        print(
            "error: socrates needs a TTY for the interview. "
            "Re-run from an interactive terminal.",
            file=sys.stderr,
        )
        return 2

    _print_intro(target.name)
    interview = Interview(
        answers_path=target / ".socrates-answers.json",
        project_name=target.name,
        resume=args.resume,
        editor=args.editor,
    )
    try:
        interview.run()
    except KeyboardInterrupt:
        print(
            "\n\nInterview interrupted. Answers so far are saved. "
            "Re-run with --resume to pick up where you left off.",
            file=sys.stderr,
        )
        return 130

    if args.no_render:
        print("\nSkipping render (--no-render). Answers saved.")
        return 0

    written = render_all(target, interview.answers)
    print(f"\nWrote {len(written)} planning files into {target}.")
    _print_outro(target, interview.answers)
    return 0


def _print_intro(project: str) -> None:
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                            120xSocrates                              ║")
    print("║                                                                      ║")
    print("║          Socratic interview for 120x Operators Kit projects          ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"Project: {project}")
    print()
    print("How this works:")
    print("  • You'll be asked ~18 questions, grouped by section.")
    print("  • For multi-line answers, type your text and finish with a single '.'")
    print("  • For list answers, one item per line; empty line to finish.")
    print("  • Press Ctrl-C anytime — your answers are saved; resume with --resume.")
    print()


def _print_outro(target: Path, answers: dict[str, Any]) -> None:
    qs = answers.get("open_questions") or []
    print()
    print("Next steps:")
    print(f"  1. cd {target}")
    print("  2. Review planning/ — push back on anything that does not match reality.")
    if qs:
        print("  3. Send planning/QUESTIONS.md to your Architect (Claude Chat / ChatGPT):")
        for q in qs:
            print(f"       - {q}")
    else:
        print("  3. Open a session with your Architect to draft Sprint 002.")
    print(f"  4. When the planning is settled, run: socrates audit {target}")
    print()
    print("The handoff is a folder, not a conversation.")
    print()


# ---------------------------------------------------------------------------
# `audit` subcommand
# ---------------------------------------------------------------------------


def _cmd_timeline(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    events = build_timeline(project)
    print(format_timeline(events))
    return 0


def _cmd_ship(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    findings = preflight(project)
    print(format_preflight(findings))
    if any(f.result is CheckResult.FAIL for f in findings):
        return 1
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    return record_decision(project, args.text)


def _cmd_pack(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    kwargs = {
        "include_sprint": args.sprint,
        "include_philosophy": args.include_philosophy,
        "kit_path": args.kit_path,
        "format": args.pack_format,
    }
    try:
        if args.stdout:
            print(build_pack(project, **kwargs))
            return 0
        target = write_pack(project, **kwargs)
    except RuntimeError as exc:
        # Raised by --format html when the `markdown` package is missing.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {target}")
    return 0


def _cmd_patterns(args: argparse.Namespace) -> int:
    if args.patterns_command != "review":
        print(f"error: unknown patterns subcommand: {args.patterns_command}",
              file=sys.stderr)
        return 2
    root: Path = args.path.expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    report = review_patterns(root, use_cache=not args.no_cache)
    print(format_pattern_report(report))
    return 1 if report.findings else 0


def _cmd_status(args: argparse.Namespace) -> int:
    root: Path = args.path.expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    if not looks_like_companyos(root):
        print(
            f"warning: {root} does not look like a CompanyOS root "
            f"(expected builds/, patterns/, and AGENTS.md). "
            f"Did you mean to run this against the parent of {root.name}?",
            file=sys.stderr,
        )
    rows = companyos_status(root)
    print(format_status(rows))
    # Exit 1 if any project has audit errors — useful in CI.
    any_errors = any(r.audit_errors > 0 for r in rows)
    return 1 if any_errors else 0


def _cmd_onboard(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    if args.stdout:
        print(synthesize_welcome(project))
        return 0
    target = write_welcome(project)
    print(f"Wrote {target}")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    if not is_interactive():
        print(
            "error: socrates extract needs a TTY for the interview.",
            file=sys.stderr,
        )
        return 2
    code, _ = run_extract(
        project,
        patterns_dir=args.patterns_dir,
        resume=args.resume,
        editor=args.editor,
    )
    return code


def _cmd_companyos(args: argparse.Namespace) -> int:
    target: Path = args.path.expanduser().resolve()
    try:
        written = scaffold_companyos(target)
    except (FileExistsError, NotADirectoryError) as e:
        # scaffold_companyos can now raise NotADirectoryError when the
        # target exists as a regular file. Catch it here so the CLI
        # surfaces a clean error instead of a Python stacktrace.
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"Scaffolded CompanyOS at: {target}")
    print(f"  Wrote {len(written)} files across {len(set(p.parent for p in written))} folders.")
    print()
    print("Next steps:")
    print(f"  1. cd {target}")
    print("  2. Read AGENTS.md.")
    print("  3. From here, start projects with: socrates init builds/<project-slug>")
    return 0


def _cmd_journal(args: argparse.Namespace) -> int:
    path: Path = args.path.expanduser().resolve()
    if not path.is_dir():
        print(f"error: {path} is not a directory", file=sys.stderr)
        return 2
    return create_or_open_entry(path, show=args.show, list_all=args.list_all)


def _cmd_audit(args: argparse.Namespace) -> int:
    path: Path = args.path.expanduser().resolve()
    if not path.is_dir():
        print(f"error: {path} is not a directory", file=sys.stderr)
        return 2

    # Mode resolution: explicit flag beats auto-detection.
    if args.companyos:
        companyos = True
    elif args.project:
        companyos = False
    else:
        companyos = looks_like_companyos(path)

    report = run_audit(path, companyos=companyos)
    output = format_report(report, as_json=args.json)
    print(output)

    has_errors = any(f.severity is Severity.ERROR for f in report.findings)
    has_warnings = any(f.severity is Severity.WARNING for f in report.findings)
    if has_errors:
        return 1
    if has_warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
