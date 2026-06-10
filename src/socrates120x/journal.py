"""The `socrates journal` subcommand — append-only daily log."""

from __future__ import annotations

import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

from socrates120x.prompting import editor_command

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
