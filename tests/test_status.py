"""Tests for the CompanyOS status dashboard."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x.companyos import scaffold_companyos
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold
from socrates120x.status import companyos_status, format_status


def _populate_build(builds_dir: Path, name: str, *, tagline: str = "demo") -> Path:
    project = builds_dir / name
    scaffold(project)
    render_all(project, {
        "project_name": name, "client": "Acme", "tagline": tagline,
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [], "decisions": [], "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return project


@pytest.fixture
def company(tmp_path: Path) -> Path:
    root = tmp_path / "120x"
    scaffold_companyos(root)
    return root


def test_status_lists_every_build(company: Path) -> None:
    _populate_build(company / "builds", "alpha")
    _populate_build(company / "builds", "beta")
    rows = companyos_status(company)
    names = [r.name for r in rows]
    assert "alpha" in names
    assert "beta" in names


def test_status_extracts_tagline(company: Path) -> None:
    _populate_build(company / "builds", "alpha", tagline="A specific alpha tagline.")
    rows = companyos_status(company)
    assert rows[0].tagline == "A specific alpha tagline."


def test_status_reports_state_freshness(company: Path) -> None:
    project = _populate_build(company / "builds", "alpha")
    state = project / "planning" / "STATE.md"
    old = (_dt.date.today() - _dt.timedelta(days=20)).isoformat()
    state.write_text(f"# STATE\n\n_Last updated: {old}_\n")
    rows = companyos_status(company)
    assert rows[0].state_age_days == 20


def test_status_reports_journal_freshness(company: Path) -> None:
    project = _populate_build(company / "builds", "alpha")
    journal_dir = project / "planning" / "journal"
    old = _dt.date.today() - _dt.timedelta(days=3)
    (journal_dir / f"{old.isoformat()}.md").write_text("entry")
    rows = companyos_status(company)
    assert rows[0].journal_age_days == 3


def test_status_no_journal_means_none(company: Path) -> None:
    _populate_build(company / "builds", "alpha")
    rows = companyos_status(company)
    assert rows[0].journal_age_days is None


def test_format_status_renders_table(company: Path) -> None:
    _populate_build(company / "builds", "alpha")
    rows = companyos_status(company)
    text = format_status(rows, use_color=False)
    assert "alpha" in text
    assert "project" in text  # header row
    assert "sprint" in text


def test_format_status_empty_input() -> None:
    text = format_status([], use_color=False)
    assert "no project" in text.lower()


# ---------------------------------------------------------------------------
# has_extract correctness (bugfix/status-extract-strict-source-match)
# ---------------------------------------------------------------------------


def test_has_extract_true_when_pattern_source_matches(company: Path) -> None:
    _populate_build(company / "builds", "alpha")
    (company / "patterns" / "CANDIDATE-x.md").write_text(
        "# Pattern: x\n\n"
        "| | |\n|---|---|\n"
        "| **Source project** | `alpha` |\n",
        encoding="utf-8",
    )
    rows = companyos_status(company)
    by_name = {r.name: r for r in rows}
    assert by_name["alpha"].has_extract is True


def test_has_extract_false_when_only_mentioned_in_war_story(company: Path) -> None:
    """Bug: previous loose `` `name` `` substring match would mark `alpha`
    as extracted just because pattern `y` (sourced from beta) mentioned
    `` `alpha` `` in its war story / 'see also' section. Now only the
    explicit Source-project line counts.
    """
    _populate_build(company / "builds", "alpha")
    _populate_build(company / "builds", "beta")
    # Pattern y is SOURCED FROM beta but mentions alpha in body content.
    (company / "patterns" / "CANDIDATE-y.md").write_text(
        "# Pattern: y\n\n"
        "| | |\n|---|---|\n"
        "| **Source project** | `beta` |\n\n"
        "## War story\n\nSimilar trick once worked on `alpha`; see that project.\n",
        encoding="utf-8",
    )
    rows = companyos_status(company)
    by_name = {r.name: r for r in rows}
    # beta IS extracted (it's the actual source).
    assert by_name["beta"].has_extract is True
    # alpha is NOT extracted — the only mention is in beta's war story.
    assert by_name["alpha"].has_extract is False, (
        "regression: status falsely reports `alpha` as extracted because "
        "a different pattern's war story mentioned it in backticks"
    )
