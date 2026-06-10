"""Tests for the onboard subcommand."""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x.onboard import _top_bullets, synthesize_welcome, write_welcome
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


def _clean_answers() -> dict:
    return {
        "project_name": "demo",
        "client": "Acme Wholesale",
        "tagline": "Automates the quarterly rebate calculation.",
        "business_goal": "Cut the manual rebate process to under an hour.",
        "tech_stack": "Python + Supabase",
        "users": ["Operations manager"],
        "current_process": "Manual spreadsheet copy-paste.",
        "terminology": ["rebate cycle — quarterly window"],
        "business_rules": ["Money is stored in integer cents"],
        "decisions": [
            "Supabase over self-hosted — client already has an account",
            "File-drop ingestion — no API available",
            "Streamlit over React — three users, ship speed wins",
            "Sentry for error tracking — free tier sufficient",
        ],
        "out_of_scope": ["Mobile app", "Real-time sync"],
        "risks": [
            "Vendor sheets change column order between quarters",
            "Historical data has inconsistent units",
            "TMS export schema is undocumented",
            "Driver paper sheets get water-damaged",
        ],
        "fragile_inputs": "",
        "open_questions": [
            "Who owns rebate disputes?",
            "Is the variance threshold final?",
            "What date format does finance want?",
            "Cap on rebate per vendor?",
        ],
        "sprint1_goal": "",
        "sprint1_acceptance": ["DOMAIN.md in client terms"],
        "sprint1_inspect": [],
        "state_current": "Sprint 001 interview complete.",
        "state_next": "Architect review.",
        "state_blockers": [],
    }


@pytest.fixture
def clean_project(tmp_path: Path) -> Path:
    target = tmp_path / "demo"
    scaffold(target)
    render_all(target, _clean_answers())
    return target


def test_welcome_contains_load_bearing_summary(clean_project: Path) -> None:
    body = synthesize_welcome(clean_project)
    assert "WELCOME — demo" in body
    assert "Acme Wholesale" in body
    assert "rebate calculation" in body.lower()
    # Top-3 truncation
    assert "Supabase over self-hosted" in body
    assert "File-drop ingestion" in body
    # The 4th decision (Sentry) should NOT appear — we cap at 3.
    assert "Sentry" not in body


def test_welcome_includes_questions_and_risks(clean_project: Path) -> None:
    body = synthesize_welcome(clean_project)
    assert "rebate disputes" in body
    assert "vendor sheets" in body.lower()
    # Out of scope
    assert "Mobile app" in body


def test_welcome_points_at_active_sprint(clean_project: Path) -> None:
    body = synthesize_welcome(clean_project)
    assert "001-discovery-architecture" in body
    assert "requirements.md" in body


def test_welcome_handles_missing_planning_files(tmp_path: Path) -> None:
    target = tmp_path / "skeleton"
    target.mkdir()
    # No planning files at all.
    body = synthesize_welcome(target)
    # Should produce *something* without crashing.
    assert "WELCOME" in body
    assert "skeleton" in body


def test_write_welcome_creates_file(clean_project: Path) -> None:
    target = write_welcome(clean_project)
    assert target == clean_project / "WELCOME.md"
    assert target.is_file()
    assert "WELCOME — demo" in target.read_text(encoding="utf-8")


def test_top_bullets_extracts_first_n() -> None:
    text = """# header

## Other stuff
- ignored

## Risks
- first risk
- second risk
- third risk
- fourth risk

## Next section
- not in scope
"""
    bullets = _top_bullets(text, "Risks", 2)
    assert bullets == ["first risk", "second risk"]


def test_welcome_prefers_answers_json_when_present(clean_project: Path) -> None:
    """If .socrates-answers.json exists, the synthesis should use it directly.

    Verified by writing an answers file that contradicts the rendered markdown:
    the WELCOME should reflect the JSON, not the markdown.
    """
    import json
    answers = _clean_answers()
    answers["client"] = "JsonOnlyCo"
    answers["decisions"] = ["JSON-only decision A — proof", "JSON-only decision B — proof"]
    (clean_project / ".socrates-answers.json").write_text(json.dumps(answers), encoding="utf-8")

    body = synthesize_welcome(clean_project)
    assert "JsonOnlyCo" in body
    assert "JSON-only decision A" in body
    # The markdown DECISIONS.md still has 'Supabase over self-hosted' — but
    # the JSON wins, so that string should NOT appear.
    assert "Supabase over self-hosted" not in body


def test_welcome_falls_back_to_markdown_when_no_json(clean_project: Path) -> None:
    """When .socrates-answers.json is absent, fall through to regex parsing."""
    answers_path = clean_project / ".socrates-answers.json"
    if answers_path.exists():
        answers_path.unlink()
    body = synthesize_welcome(clean_project)
    # Markdown-parsed path: should still pick up the rendered DECISIONS.md content.
    assert "Supabase over self-hosted" in body


def test_top_bullets_skips_placeholder_lines() -> None:
    text = """## Risks

- _(none recorded — italic placeholder)_
- real risk one
"""
    # Placeholder italics start with "- _" and we skip those.
    bullets = _top_bullets(text, "Risks", 3)
    assert bullets == ["real risk one"]


# ---------------------------------------------------------------------------
# Active-sprint derivation (bugfix/onboard-derive-active-sprint-from-dirs)
# ---------------------------------------------------------------------------


def test_synthesize_picks_highest_numbered_sprint_not_001(tmp_path) -> None:
    """A project that has progressed past 001 must not have its WELCOME.md
    still claim sprint 001 just because answers.json was the init record.
    """
    from socrates120x.onboard import synthesize_welcome
    from socrates120x.render import render_all
    from socrates120x.scaffold import scaffold

    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "Acme", "tagline": "demo",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [], "decisions": [], "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [], "sprint1_inspect": [],
        "state_current": "", "state_next": "", "state_blockers": [],
    })
    # Add a sprint 005 directory after init.
    (p / "planning" / "sprints" / "005-rebate-engine").mkdir()
    (p / "planning" / "sprints" / "005-rebate-engine" / "requirements.md").write_text(
        "# requirements\n", encoding="utf-8",
    )

    text = synthesize_welcome(p)
    # WELCOME.md must call out sprint 005 — NOT 001.
    assert "005" in text, "WELCOME.md did not reflect sprint 005"
    assert "Rebate Engine" in text
    # The old hardcoded label must NOT appear.
    assert "001 — Discovery & Architecture" not in text


def test_synthesize_ignores_non_canonical_sprint_dirs(tmp_path) -> None:
    """Stray dirs like `draft/`, `backup-002/`, `notes/` must NOT be picked
    as the active sprint — they don't match the canonical NNN- prefix."""
    from socrates120x.onboard import synthesize_welcome
    from socrates120x.render import render_all
    from socrates120x.scaffold import scaffold

    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "Acme", "tagline": "demo",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [], "decisions": [], "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [], "sprint1_inspect": [],
        "state_current": "", "state_next": "", "state_blockers": [],
    })
    sprints = p / "planning" / "sprints"
    (sprints / "draft").mkdir()
    (sprints / "backup-002").mkdir()  # leading char is not a digit
    (sprints / "notes").mkdir()

    text = synthesize_welcome(p)
    # Only 001 (from init) is canonical — should be the active label.
    assert "001" in text
    # Stray dirs must not appear as a sprint label.
    assert "draft" not in text
    assert "backup-002" not in text
    assert "notes" not in text


# ---------------------------------------------------------------------------
# Post-init decisions surface in WELCOME.md
# (bugfix/onboard-includes-post-init-decisions)
# ---------------------------------------------------------------------------


def test_synthesize_includes_post_init_decisions_from_decide(tmp_path) -> None:
    """`socrates decide` appends to DECISIONS.md after init. `socrates
    onboard` must surface those — otherwise WELCOME.md stays stale and
    new collaborators read decisions that were superseded weeks ago."""
    from socrates120x.decide import record_decision
    from socrates120x.onboard import synthesize_welcome
    from socrates120x.render import render_all
    from socrates120x.scaffold import scaffold

    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "Acme", "tagline": "demo",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [],
        "decisions": ["Initial choice X — because Y"],
        "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    # Operator adds a fresh decision via the dated path.
    record_decision(p, "Adopted DuckDB — outperformed Postgres on the q4 sample")

    text = synthesize_welcome(p)
    assert "Adopted DuckDB" in text, (
        "WELCOME.md ignored a post-init decision added via `socrates decide`"
    )
    # Both the init decision AND the post-init one should be visible.
    assert "Initial choice X" in text


def test_synthesize_orders_post_init_decisions_first(tmp_path) -> None:
    """Recency matters — the post-init decision should appear ABOVE the
    init-time decision in WELCOME.md so new readers see the latest first."""
    from socrates120x.decide import record_decision
    from socrates120x.onboard import synthesize_welcome
    from socrates120x.render import render_all
    from socrates120x.scaffold import scaffold

    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "Acme", "tagline": "demo",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [],
        "decisions": ["ORIGINAL choice — old reasoning"],
        "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    record_decision(p, "NEWER reversal — chose other thing after experiment")

    text = synthesize_welcome(p)
    assert text.index("NEWER reversal") < text.index("ORIGINAL choice"), (
        "post-init decision should appear above the init-time decision"
    )
