"""Tests for socrates timeline."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x.render import render_all
from socrates120x.scaffold import scaffold
from socrates120x.timeline import EventKind, build_timeline, format_timeline


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "demo"
    scaffold(p)
    render_all(
        p,
        {
            "project_name": "demo",
            "client": "Acme",
            "tagline": "t",
            "business_goal": "g",
            "tech_stack": "Python",
            "users": [],
            "current_process": "",
            "terminology": [],
            "business_rules": [],
            "decisions": [],
            "out_of_scope": [],
            "risks": [],
            "fragile_inputs": "",
            "open_questions": [],
            "sprint1_goal": "",
            "sprint1_acceptance": [],
            "sprint1_inspect": [],
            "state_current": "",
            "state_next": "",
            "state_blockers": [],
        },
    )
    return p


def test_timeline_includes_journal_entries(project: Path) -> None:
    journal = project / "planning" / "journal"
    yesterday = _dt.date.today() - _dt.timedelta(days=1)
    (journal / f"{yesterday.isoformat()}.md").write_text(
        "# Journal\n\nFixed the parser bug.\n", encoding="utf-8"
    )
    events = build_timeline(project)
    journal_events = [e for e in events if e.kind is EventKind.JOURNAL]
    assert len(journal_events) == 1
    assert journal_events[0].date == yesterday
    assert "Fixed the parser bug" in journal_events[0].detail


def test_timeline_includes_sprint_entries(project: Path) -> None:
    events = build_timeline(project)
    sprint_events = [e for e in events if e.kind is EventKind.SPRINT]
    assert len(sprint_events) == 1
    assert "001-discovery-architecture" in sprint_events[0].title


def test_timeline_extracts_dated_decisions(project: Path) -> None:
    decisions = project / "planning" / "DECISIONS.md"
    decisions.write_text(
        "## Decisions captured\n\n"
        "- **Supabase over Postgres — client preference (2026-04-01)**\n"
        "- An undated decision should NOT appear in the timeline.\n",
        encoding="utf-8",
    )
    events = build_timeline(project)
    decision_events = [e for e in events if e.kind is EventKind.DECISION]
    assert len(decision_events) == 1
    assert decision_events[0].date == _dt.date(2026, 4, 1)
    assert "Supabase" in decision_events[0].title


def test_timeline_sorts_chronologically(project: Path) -> None:
    journal = project / "planning" / "journal"
    days_ago_3 = _dt.date.today() - _dt.timedelta(days=3)
    days_ago_1 = _dt.date.today() - _dt.timedelta(days=1)
    (journal / f"{days_ago_3.isoformat()}.md").write_text("older", encoding="utf-8")
    (journal / f"{days_ago_1.isoformat()}.md").write_text("newer", encoding="utf-8")
    events = build_timeline(project)
    dates = [e.date for e in events if e.kind is EventKind.JOURNAL]
    assert dates == sorted(dates)


def test_format_timeline_empty() -> None:
    text = format_timeline([], use_color=False)
    assert "no timeline events" in text


def test_format_timeline_renders_events(project: Path) -> None:
    yesterday = _dt.date.today() - _dt.timedelta(days=1)
    (project / "planning" / "journal" / f"{yesterday.isoformat()}.md").write_text(
        "note", encoding="utf-8"
    )
    events = build_timeline(project)
    text = format_timeline(events, use_color=False)
    assert yesterday.isoformat() in text
    assert "[journal]" in text
