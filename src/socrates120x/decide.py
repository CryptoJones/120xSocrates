"""The `socrates decide` subcommand — append a properly dated decision.

Decisions captured during `socrates init` carry the date of the init
interview. Decisions made later (Sprint 003, Sprint 008, mid-incident,
etc.) deserve the actual date they were made. This subcommand appends
one decision to `planning/DECISIONS.md`, dating it today and putting it
in a "Decisions added after init" section so the Sprint 001 history
stays distinct.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

from socrates120x._atomic import locked_read_modify_write

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
