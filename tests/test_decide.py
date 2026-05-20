"""Tests for socrates decide."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x.decide import record_decision
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "Acme", "tagline": "demo",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [],
        "decisions": ["Initial choice X — reason"],
        "out_of_scope": ["Mobile"],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return p


def test_decide_appends_dated_bullet(project: Path) -> None:
    code = record_decision(project, "New choice Y — because Z")
    assert code == 0
    body = (project / "planning" / "DECISIONS.md").read_text()
    today = _dt.date.today().isoformat()
    assert f"New choice Y — because Z ({today})" in body


def test_decide_creates_post_init_section(project: Path) -> None:
    record_decision(project, "First post-init choice")
    body = (project / "planning" / "DECISIONS.md").read_text()
    assert "## Decisions added after init" in body
    # The new section must appear BEFORE the out-of-scope section.
    post_init_idx = body.index("## Decisions added after init")
    out_of_scope_idx = body.index("## Explicitly out of scope")
    assert post_init_idx < out_of_scope_idx


def test_decide_reuses_existing_post_init_section(project: Path) -> None:
    record_decision(project, "First post-init choice")
    record_decision(project, "Second post-init choice")
    body = (project / "planning" / "DECISIONS.md").read_text()
    # There should be exactly ONE 'Decisions added after init' heading.
    assert body.count("## Decisions added after init") == 1
    # Both bullets should be present in that section.
    assert "First post-init choice" in body
    assert "Second post-init choice" in body
    # And in order.
    assert body.index("First post-init") < body.index("Second post-init")


def test_decide_preserves_sprint1_section(project: Path) -> None:
    record_decision(project, "Post-init choice")
    body = (project / "planning" / "DECISIONS.md").read_text()
    # The original Sprint 001 section must still exist with its decision.
    assert "## Decisions captured during Sprint 001 discovery" in body
    assert "Initial choice X — reason" in body


def test_decide_rejects_empty_text(project: Path) -> None:
    code = record_decision(project, "   ")
    assert code == 2


def test_decide_errors_when_no_decisions_md(tmp_path: Path) -> None:
    code = record_decision(tmp_path, "anything")
    assert code == 2


def test_decide_collapses_internal_whitespace_to_keep_bullet_single_line(
    project: Path,
) -> None:
    """A multi-line decision text would otherwise leave the closing `**`
    on a different line, breaking the markdown bullet. Collapse all
    runs of whitespace to a single space."""
    code = record_decision(
        project,
        "first line\n  second line\t\twith tabs\n\n\nthird line",
    )
    assert code == 0
    body = (project / "planning" / "DECISIONS.md").read_text()
    today = _dt.date.today().isoformat()
    expected_bullet = f"- **first line second line with tabs third line ({today})**"
    assert expected_bullet in body
    # And the literal multi-line form must NOT appear:
    assert "\n  second line" not in body


def test_decide_timeline_picks_up_new_decision(project: Path) -> None:
    """End-to-end: the date stamp `socrates decide` writes is the one
    `socrates timeline` reads."""
    from socrates120x.timeline import EventKind, build_timeline
    record_decision(project, "Cross-feature choice — for posterity")
    events = build_timeline(project)
    decisions = [e for e in events if e.kind is EventKind.DECISION]
    assert any("Cross-feature choice" in e.title for e in decisions)
    assert any(e.date == _dt.date.today() for e in decisions)
