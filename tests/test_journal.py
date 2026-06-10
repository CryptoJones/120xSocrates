"""Tests for the journal subcommand."""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from socrates120x.journal import create_or_open_entry
from socrates120x.scaffold import scaffold


@pytest.fixture
def project(tmp_path: Path) -> Path:
    target = tmp_path / "demo"
    scaffold(target)
    return target


def test_journal_creates_today_entry(project: Path) -> None:
    def no_op_run(cmd: list[str], check: bool = True) -> Any:  # noqa: ARG001
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with (
        patch.object(subprocess, "run", side_effect=no_op_run),
        patch.dict(os.environ, {"EDITOR": "fake-editor"}),
    ):
        code = create_or_open_entry(project)

    today = _dt.date.today().isoformat()
    entry = project / "planning" / "journal" / f"{today}.md"
    assert code == 0
    assert entry.is_file()
    body = entry.read_text(encoding="utf-8")
    assert today in body
    assert "What happened" in body


def test_journal_list_empty_then_with_entry(project: Path, capsys: pytest.CaptureFixture) -> None:
    code = create_or_open_entry(project, list_all=True)
    assert code == 0
    out = capsys.readouterr().out
    assert "no journal entries yet" in out

    today = _dt.date.today().isoformat()
    (project / "planning" / "journal" / f"{today}.md").write_text("entry", encoding="utf-8")
    code = create_or_open_entry(project, list_all=True)
    out = capsys.readouterr().out
    assert today in out


def test_journal_show_prints_latest(project: Path, capsys: pytest.CaptureFixture) -> None:
    today = _dt.date.today().isoformat()
    (project / "planning" / "journal" / f"{today}.md").write_text("hello journal", encoding="utf-8")
    code = create_or_open_entry(project, show=True)
    assert code == 0
    out = capsys.readouterr().out
    assert "hello journal" in out


def test_journal_errors_on_non_project(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    code = create_or_open_entry(tmp_path)
    assert code == 2
    err = capsys.readouterr().err
    assert "does not exist" in err


# ---------------------------------------------------------------------------
# Only dated entries are listed/shown
# (bugfix/journal-only-dated-entries)
# ---------------------------------------------------------------------------


def test_journal_list_ignores_non_dated_files(tmp_path, capsys) -> None:
    """`socrates journal --list` must NOT enumerate notes.md, ideas.md,
    drafts/ etc. that the operator may have dropped into the journal dir.
    Only files named YYYY-MM-DD.md count."""
    from socrates120x.journal import create_or_open_entry
    from socrates120x.scaffold import scaffold

    p = tmp_path / "demo"
    scaffold(p)
    journal_dir = p / "planning" / "journal"
    # Create two real dated entries.
    (journal_dir / "2025-09-01.md").write_text("# entry", encoding="utf-8")
    (journal_dir / "2026-01-15.md").write_text("# entry", encoding="utf-8")
    # And several decoy files.
    (journal_dir / "notes.md").write_text("# random notes", encoding="utf-8")
    (journal_dir / "ideas.md").write_text("# brainstorm", encoding="utf-8")
    (journal_dir / "2025-9-1.md").write_text("# unpadded date", encoding="utf-8")  # not canonical

    rc = create_or_open_entry(p, list_all=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "2025-09-01" in out
    assert "2026-01-15" in out
    assert "notes" not in out
    assert "ideas" not in out
    # README.md (already excluded by original code) stays excluded:
    assert "README" not in out
    # Unpadded date (2025-9-1) is not canonical:
    assert "2025-9-1" not in out


def test_journal_show_picks_latest_dated_not_arbitrary(tmp_path, capsys) -> None:
    """`--show` must pick the LATEST dated entry, not whatever sorts last
    alphabetically (which would include notes.md)."""
    from socrates120x.journal import create_or_open_entry
    from socrates120x.scaffold import scaffold

    p = tmp_path / "demo"
    scaffold(p)
    journal_dir = p / "planning" / "journal"
    (journal_dir / "2025-01-01.md").write_text("# old entry", encoding="utf-8")
    (journal_dir / "2026-06-15.md").write_text("# latest dated entry body", encoding="utf-8")
    # Decoy: 'zzz.md' would sort AFTER any date if we matched all .md.
    (journal_dir / "zzz.md").write_text("# decoy notes — should NOT be shown", encoding="utf-8")

    rc = create_or_open_entry(p, show=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "latest dated entry body" in out
    assert "decoy" not in out
