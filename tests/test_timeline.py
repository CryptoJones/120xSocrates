"""Tests for socrates timeline."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x import EventKind, build_timeline, format_timeline, render_all, scaffold


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "Acme", "tagline": "t",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [], "decisions": [], "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return p


def test_sprint_date_prefers_labeled_stamp(tmp_path: Path) -> None:
    # Regression (#31): a labeled date stamp in the sprint files is preferred
    # over directory mtime (which a clone/restore resets).
    from socrates120x.operate import _sprint_date

    sprint = tmp_path / "001-discovery"
    sprint.mkdir()
    (sprint / "requirements.md").write_text(
        "# Requirements\n\nLast updated: 2025-01-15\n", encoding="utf-8"
    )
    assert _sprint_date(sprint) == _dt.date(2025, 1, 15)


def test_sprint_date_falls_back_to_mtime(tmp_path: Path) -> None:
    from socrates120x.operate import _sprint_date

    sprint = tmp_path / "002-build"
    sprint.mkdir()
    (sprint / "requirements.md").write_text("# Requirements\n\nno date here\n", encoding="utf-8")
    assert _sprint_date(sprint) is not None  # mtime fallback


def test_timeline_includes_journal_entries(project: Path) -> None:
    journal = project / "planning" / "journal"
    yesterday = _dt.date.today() - _dt.timedelta(days=1)
    (journal / f"{yesterday.isoformat()}.md").write_text(
        "# Journal\n\nFixed the parser bug.\n"
    , encoding="utf-8")
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
        "- An undated decision should NOT appear in the timeline.\n"
    , encoding="utf-8")
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
    (project / "planning" / "journal" / f"{yesterday.isoformat()}.md").write_text("note", encoding="utf-8")
    events = build_timeline(project)
    text = format_timeline(events, use_color=False)
    assert yesterday.isoformat() in text
    assert "[journal]" in text


def test_decision_with_user_date_in_body_uses_trailing_recording_date(
    project: Path,
) -> None:
    """User decision text can mention a date in parens (e.g. a deadline).
    The PREVIOUS unanchored regex took the FIRST date in the line, which
    was the user's date, not the date the decision was recorded. Anchor
    to the trailing `)**` so the recording date wins."""
    decisions = project / "planning" / "DECISIONS.md"
    decisions.write_text(
        decisions.read_text(encoding="utf-8")
        + "\n\n## Decisions added after init\n\n"
        + "- **Migrate by (2024-12-31) for compliance (2026-05-20)**\n"
    , encoding="utf-8")
    events = build_timeline(project)
    decision_events = [e for e in events if e.kind is EventKind.DECISION]
    # The decision must be dated 2026-05-20 (the recording date),
    # NOT 2024-12-31 (the user's deadline date inside the bullet text).
    matching = [e for e in decision_events if "Migrate by" in e.title]
    assert matching, "decision was not detected at all"
    assert matching[0].date == _dt.date(2026, 5, 20), (
        f"expected recording date 2026-05-20; got {matching[0].date} — "
        f"likely picked the user-typed (2024-12-31) at the front of the line"
    )
    # The user's date in the body should be preserved in the rendered title
    # (we only strip the trailing recording stamp).
    assert "2024-12-31" in matching[0].title


def test_decision_with_no_trailing_stamp_falls_back_to_any_date(
    project: Path,
) -> None:
    """Pre-fix files / hand-edited bullets may have just `(YYYY-MM-DD)`
    somewhere in the line with no closing `**`. Still detect them via
    the unanchored fallback."""
    decisions = project / "planning" / "DECISIONS.md"
    decisions.write_text(
        decisions.read_text(encoding="utf-8")
        + "\n\n## Decisions added after init\n\n"
        + "- legacy bullet style (2025-03-15)\n"
    , encoding="utf-8")
    events = build_timeline(project)
    decision_events = [e for e in events if e.kind is EventKind.DECISION]
    matching = [e for e in decision_events if "legacy bullet" in e.title]
    assert matching
    assert matching[0].date == _dt.date(2025, 3, 15)
