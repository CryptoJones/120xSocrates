"""Reusable terminal prompting primitives.

Factored out of `interview.py` so that any subcommand needing structured
question-and-answer flow (init, extract, future plugins) can share the same
input handling, list confirmations, multiline `$EDITOR` mode, etc.

Nothing in here knows about the 120x methodology — it is pure I/O.
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
