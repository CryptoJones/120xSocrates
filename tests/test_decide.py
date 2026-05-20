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


def test_decide_timeline_picks_up_new_decision(project: Path) -> None:
    """End-to-end: the date stamp `socrates decide` writes is the one
    `socrates timeline` reads."""
    from socrates120x.timeline import EventKind, build_timeline
    record_decision(project, "Cross-feature choice — for posterity")
    events = build_timeline(project)
    decisions = [e for e in events if e.kind is EventKind.DECISION]
    assert any("Cross-feature choice" in e.title for e in decisions)
    assert any(e.date == _dt.date.today() for e in decisions)


# ---------------------------------------------------------------------------
# Concurrent decide invocations (refactor/shared-atomic-write-and-decide-lock)
# ---------------------------------------------------------------------------


def _concurrent_decide(project_str: str, text: str, hold_ms: int) -> None:
    """Worker that mimics a slow record_decision under the lock."""
    import datetime as _dt
    import time as _t

    from socrates120x._atomic import locked_read_modify_write
    from socrates120x.decide import _insert_decision

    decisions_path = _Path(project_str) / "planning" / "DECISIONS.md"
    today = _dt.date.today().isoformat()
    cleaned = " ".join(text.split())
    bullet = f"- **{cleaned} ({today})**"

    def mutate(current: str) -> str:
        _t.sleep(hold_ms / 1000)  # widen the race window
        return _insert_decision(current, bullet)

    locked_read_modify_write(decisions_path, mutate)


# Imported lazily so the worker can reach it; using a private alias to
# avoid shadowing the project's existing `Path` imports.
import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402


@pytest.mark.skipif(
    _sys.platform == "win32",
    reason="POSIX fcntl-based locking; Windows path is a graceful no-op",
)
def test_decide_concurrent_writes_keep_both_decisions(project: Path) -> None:
    """Two `socrates decide` invocations running concurrently must not
    cause a lost update — both decisions land in DECISIONS.md."""
    from multiprocessing import Process

    p1 = Process(target=_concurrent_decide, args=(str(project), "decision ALPHA", 250))
    p2 = Process(target=_concurrent_decide, args=(str(project), "decision BETA", 250))
    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)
    assert p1.exitcode == 0 and p2.exitcode == 0

    body = (project / "planning" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "decision ALPHA" in body, "ALPHA decision was lost"
    assert "decision BETA" in body, "BETA decision was lost"
