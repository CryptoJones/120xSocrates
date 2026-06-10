"""CLI-level tests for `socrates pack --format`.

The argparse wiring in cli.py was previously untested at the CLI level
(the project has unit tests for build_pack/write_pack but nothing that
exercises the actual `socrates pack` argparse path). These tests drive
``socrates120x.cli.main`` end-to-end so a regression in the CLI plumbing
(dest names, choices, defaults, the markdown-missing error path) gets
caught in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x.cli import main
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "cli-demo"
    scaffold(p)
    render_all(p, {
        "project_name": "cli-demo", "client": "AcmeCorp", "tagline": "demo",
        "business_goal": "goal", "tech_stack": "Python",
        "users": ["op"], "current_process": "manual", "terminology": [],
        "business_rules": [], "decisions": ["choice — reason"], "out_of_scope": [],
        "risks": ["risk one"], "fragile_inputs": "", "open_questions": ["q1?"],
        "sprint1_goal": "", "sprint1_acceptance": ["one"],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return p


def test_pack_default_format_writes_md(project: Path) -> None:
    rc = main(["pack", str(project)])
    assert rc == 0
    assert (project / ".socrates-architect-pack.md").is_file()


def test_pack_format_md_explicit(project: Path) -> None:
    rc = main(["pack", str(project), "--format", "md"])
    assert rc == 0
    assert (project / ".socrates-architect-pack.md").is_file()


def test_pack_format_xml_writes_xml(project: Path) -> None:
    rc = main(["pack", str(project), "--format", "xml"])
    assert rc == 0
    target = project / ".socrates-architect-pack.xml"
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert content.startswith("<bundle ")
    assert "AcmeCorp" in content


def test_pack_format_html_writes_html(project: Path) -> None:
    rc = main(["pack", str(project), "--format", "html"])
    assert rc == 0
    target = project / ".socrates-architect-pack.html"
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert content.startswith("<!doctype html>")


def test_pack_format_stdout_xml(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["pack", str(project), "--stdout", "--format", "xml"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("<bundle ")
    # Confirm --stdout did NOT also write the file to disk.
    assert not (project / ".socrates-architect-pack.xml").exists()


def test_pack_format_rejects_unknown_value(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # argparse exits with SystemExit (rc=2) on invalid choice; main() never
    # gets to return its own code. We catch the SystemExit and inspect stderr.
    with pytest.raises(SystemExit) as exc:
        main(["pack", str(project), "--format", "json"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert "'json'" in err


def test_pack_format_html_error_when_markdown_missing(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise the CLI's RuntimeError handling for the missing-markdown path."""
    import socrates120x.pack as pack_module

    def _raise() -> None:
        raise RuntimeError(
            "--format html requires the `markdown` package. Install with "
            "`pip install socrates120x[html]` or `pip install markdown`."
        )

    monkeypatch.setattr(pack_module, "_import_markdown", _raise)
    rc = main(["pack", str(project), "--format", "html"])
    # CLI should return exit code 2 (not let the exception propagate) and
    # write the install hint to stderr.
    assert rc == 2
    err = capsys.readouterr().err
    assert "markdown" in err
    assert "pip install" in err


def test_pack_format_help_text_lists_all_choices(capsys: pytest.CaptureFixture[str]) -> None:
    # --help on argparse causes SystemExit(0); the help text goes to stdout.
    with pytest.raises(SystemExit):
        main(["pack", "--help"])
    out = capsys.readouterr().out
    assert "--format" in out
    assert "md" in out
    assert "xml" in out
    assert "html" in out
