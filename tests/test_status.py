"""Tests for the CompanyOS status dashboard."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x import companyos_status, format_status, render_all, scaffold, scaffold_companyos


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
    state.write_text(f"# STATE\n\n_Last updated: {old}_\n", encoding="utf-8")
    rows = companyos_status(company)
    assert rows[0].state_age_days == 20


def test_status_reports_journal_freshness(company: Path) -> None:
    project = _populate_build(company / "builds", "alpha")
    journal_dir = project / "planning" / "journal"
    old = _dt.date.today() - _dt.timedelta(days=3)
    (journal_dir / f"{old.isoformat()}.md").write_text("entry", encoding="utf-8")
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


def test_latest_journal_age_ignores_non_date_files(tmp_path: Path) -> None:
    # Regression (#27): a stray non-date file (notes.md) sorts lexicographically
    # above an ISO date and used to win max(stems), fail to parse, and make the
    # journal age read as unknown despite a fresh dated entry existing.
    from socrates120x.operate import _latest_journal_age_days

    journal = tmp_path / "planning" / "journal"
    journal.mkdir(parents=True)
    today = _dt.date.today().isoformat()
    (journal / f"{today}.md").write_text("entry", encoding="utf-8")
    (journal / "notes.md").write_text("scratch", encoding="utf-8")
    assert _latest_journal_age_days(tmp_path) == 0


def test_active_sprint_ignores_non_numbered_folder(tmp_path: Path) -> None:
    # Regression (#32): a stray scratch folder sorts above "001-…" but must
    # not be reported as the active sprint.
    from socrates120x.operate import _extract_active_sprint

    sprints = tmp_path / "planning" / "sprints"
    sprints.mkdir(parents=True)
    (sprints / "001-foundations").mkdir()
    (sprints / "wip-experiments").mkdir()
    assert _extract_active_sprint(tmp_path) == "001-foundations"


def test_tagline_ignores_unrelated_bold_dash(tmp_path: Path) -> None:
    # Regression (#33): an unrelated "**bold** — text" line must not hijack the
    # tagline; only the project's own "**<name>** — tagline" line counts.
    from socrates120x.operate import _project_tagline

    proj = tmp_path / "demo"
    proj.mkdir()
    (proj / "AGENTS.md").write_text(
        "# AGENTS.md — demo\n\n**Owner** — Jane (rotating)\n\n**demo** — the real tagline\n",
        encoding="utf-8",
    )
    assert _project_tagline(proj) == "the real tagline"


def test_pad_visible_counts_only_visible_chars() -> None:
    # Regression (#34): padding must measure visible width, ignoring ANSI bytes.
    import re

    from socrates120x.operate import _pad_visible

    padded = _pad_visible("\033[32mOK\033[0m", 5)
    visible = re.sub(r"\033\[[0-9;]*m", "", padded)
    assert len(visible) == 5
    assert padded.endswith("   ")
