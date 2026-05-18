"""Tests for the patterns review subcommand."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x.companyos import scaffold_companyos
from socrates120x.patterns import FindingKind, format_pattern_report, review_patterns
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


def _pattern(text_date: str, source: str, slug: str, candidate: bool = True) -> str:
    return f"""# Pattern: {slug} ({"CANDIDATE" if candidate else "promoted"})

> Demo pattern.

| | |
|---|---|
| **Kind** | demo |
| **Confidence** | 1 / 5 |
| **Extracted** | {text_date} |
| **Source project** | `{source}` |

## When this applies

When tests need it.

## The pattern

(body)
"""


@pytest.fixture
def company(tmp_path: Path) -> Path:
    root = tmp_path / "120x"
    scaffold_companyos(root)
    return root


def _make_build(company: Path, name: str) -> Path:
    project = company / "builds" / name
    scaffold(project)
    render_all(project, {
        "project_name": name, "client": "Acme", "tagline": "demo",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [], "decisions": [], "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return project


def test_patterns_review_clean_when_no_patterns(company: Path) -> None:
    report = review_patterns(company)
    assert report.findings == []
    assert report.candidates_total == 0


def test_patterns_review_flags_stale_candidate(company: Path) -> None:
    _make_build(company, "alpha")
    old = (_dt.date.today() - _dt.timedelta(days=120)).isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(old, "alpha", "validate-numbers")
    )
    report = review_patterns(company)
    kinds = {f.kind for f in report.findings}
    assert FindingKind.STALE in kinds


def test_patterns_review_flags_orphan_source(company: Path) -> None:
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "ghost-project", "x"))
    report = review_patterns(company)
    kinds = {f.kind for f in report.findings}
    assert FindingKind.ORPHAN in kinds


def test_patterns_review_quiet_when_pattern_reused_elsewhere(company: Path) -> None:
    """A pattern whose slug appears in a build other than its source is 'used'."""
    _make_build(company, "alpha")
    other = _make_build(company, "beta")
    # Mention the pattern slug in beta's STATE.
    (other / "planning" / "STATE.md").write_text(
        (other / "planning" / "STATE.md").read_text() + "\nReused: validate-numbers\n"
    )
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(today, "alpha", "validate-numbers")
    )
    report = review_patterns(company)
    # No UNUSED finding for this pattern (it appears in beta).
    unused_paths = [f.path.name for f in report.findings if f.kind == FindingKind.UNUSED]
    assert "CANDIDATE-validate-numbers.md" not in unused_paths


def test_patterns_review_flags_unused(company: Path) -> None:
    """A pattern referenced only in its source project is unused."""
    alpha = _make_build(company, "alpha")
    _make_build(company, "beta")  # exists but doesn't reference the slug
    # Mention slug in alpha (source) — but nowhere else.
    (alpha / "planning" / "STATE.md").write_text(
        (alpha / "planning" / "STATE.md").read_text() + "\nMentions validate-numbers.\n"
    )
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(today, "alpha", "validate-numbers")
    )
    report = review_patterns(company)
    unused = [f for f in report.findings if f.kind == FindingKind.UNUSED]
    assert any("validate-numbers" in f.path.name for f in unused)


def test_format_pattern_report_clean(company: Path) -> None:
    report = review_patterns(company)
    text = format_pattern_report(report, use_color=False)
    assert "no findings" in text


def test_format_pattern_report_groups_by_kind(company: Path) -> None:
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "ghost", "x"))
    report = review_patterns(company)
    text = format_pattern_report(report, use_color=False)
    assert "orphan-source" in text
