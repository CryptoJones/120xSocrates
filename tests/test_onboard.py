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
    assert "WELCOME — demo" in target.read_text()


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
    (clean_project / ".socrates-answers.json").write_text(json.dumps(answers))

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
