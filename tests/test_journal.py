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
