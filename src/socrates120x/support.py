"""Shared plumbing: terminal colors, atomic file I/O, prompting primitives.

Nothing in here knows about the 120x methodology — it is the toolbox the
rest of the package builds with.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
            # stdin is exhausted (Ctrl-D, or a redirected/closed stream).
            # The old code set raw="" and looped, which spun a CPU core
            # forever on a required field with no default — e.g. the very
            # first init question (`client`). Resolve now instead: use the
            # default if any, otherwise abort the interview by re-raising
            # (cli/extract catch EOFError, save progress, suggest --resume).
            if q.default:
                return q.default
            if q.required:
                raise
            return ""
        if not raw and q.default:
            return q.default
        if not raw and q.required:
            output_fn("   (this one is required — please answer)")
            continue
        return raw


def _ask_multiline(input_fn: InputFn, output_fn: OutputFn, q: Question) -> str:
    output_fn("   (multi-line — finish with a single '.' on its own line)")
    lines: list[str] = []
    eof = False
    while True:
        prompt = "   …  " if lines else "   ›  "
        try:
            line = input_fn(prompt)
        except EOFError:
            eof = True
            break
        if line.strip() == ".":
            break
        lines.append(line)
    text = "\n".join(lines).rstrip()
    if not text and q.default:
        output_fn("   (using default)")
        return q.default
    if not text and q.required:
        if eof:
            # Dead stream — recursing here used to climb to RecursionError.
            # Abort cleanly; the caller saves progress and suggests --resume.
            raise EOFError
        output_fn("   (this one is required — try again)")
        return _ask_multiline(input_fn, output_fn, q)
    return text


def _ask_multiline_editor(
    output_fn: OutputFn, q: Question, *, input_fn: InputFn = input, _attempt: int = 0
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
        if _attempt >= 2:
            output_fn("   (still empty after several tries — leaving this blank)")
            return ""
        output_fn("   (this one is required — re-opening editor)")
        return _ask_multiline_editor(
            output_fn, q, input_fn=input_fn, _attempt=_attempt + 1
        )
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
