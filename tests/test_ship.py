"""Tests for socrates ship."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x import CheckResult, preflight, render_all, scaffold


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "Acme", "tagline": "t",
        "business_goal": "g", "tech_stack": "Python",
        "users": ["op"], "current_process": "m", "terminology": [],
        "business_rules": [], "decisions": [], "out_of_scope": [],
        "risks": ["r"], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": ["ok"],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return p


def test_preflight_runs_all_four_checks(project: Path) -> None:
    findings = preflight(project)
    names = {f.name for f in findings}
    assert names == {"audit", "journal", "extract", "state"}


def test_preflight_journal_passes_when_today_entry_exists(project: Path) -> None:
    today = _dt.date.today().isoformat()
    (project / "planning" / "journal" / f"{today}.md").write_text("entry", encoding="utf-8")
    findings = preflight(project)
    journal = next(f for f in findings if f.name == "journal")
    assert journal.result is CheckResult.PASS


def test_preflight_journal_warns_when_no_entry(project: Path) -> None:
    findings = preflight(project)
    journal = next(f for f in findings if f.name == "journal")
    assert journal.result is CheckResult.WARN


def test_preflight_extract_warns_when_no_pattern(project: Path) -> None:
    findings = preflight(project)
    extract = next(f for f in findings if f.name == "extract")
    assert extract.result is CheckResult.WARN


def test_preflight_extract_passes_when_pattern_present(project: Path) -> None:
    (project / "patterns").mkdir(exist_ok=True)
    (project / "patterns" / "CANDIDATE-x.md").write_text(
        f"**Source project** | `{project.name}`\n"
    , encoding="utf-8")
    findings = preflight(project)
    extract = next(f for f in findings if f.name == "extract")
    assert extract.result is CheckResult.PASS


def test_preflight_state_warns_on_old_date(project: Path) -> None:
    old = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()
    (project / "planning" / "STATE.md").write_text(
        f"# STATE\n\n_Last updated: {old}_\n"
    , encoding="utf-8")
    findings = preflight(project)
    state = next(f for f in findings if f.name == "state")
    assert state.result is CheckResult.WARN
    assert "30 days" in state.message


def test_preflight_audit_fails_on_missing_required_file(project: Path) -> None:
    (project / "planning" / "QUESTIONS.md").unlink()
    findings = preflight(project)
    audit = next(f for f in findings if f.name == "audit")
    assert audit.result is CheckResult.FAIL
