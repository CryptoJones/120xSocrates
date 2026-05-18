from pathlib import Path

from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


def _sample_answers() -> dict:
    return {
        "project_name": "quarterly-rebates",
        "client": "Acme Wholesale",
        "tagline": "Automates the quarterly vendor rebate calculation that ops does manually in Excel.",
        "business_goal": "Eliminate the 3-day manual rebate process ops runs every quarter.",
        "tech_stack": "Python + Supabase",
        "users": ["Operations manager", "Finance lead"],
        "current_process": "Two analysts open vendor spreadsheets, copy values into a master sheet, run a pivot, email finance.",
        "terminology": [
            "rebate cycle — quarterly window when payouts are calculated",
            "tier A vendor — pre-approved supplier",
        ],
        "business_rules": [
            "Money is stored in integer cents, never floats",
            "A rebate below $5 is never paid out",
        ],
        "decisions": [
            "Supabase over self-hosted Postgres — client already has an account",
            "File-drop ingestion — vendors will not expose an API",
        ],
        "out_of_scope": ["Mobile app (web only)"],
        "risks": ["Vendor spreadsheets change column order between quarters"],
        "fragile_inputs": "Some historical sheets use 'rebate %' and others use 'rebate_pct' — must reconcile.",
        "open_questions": ["Who owns rebate disputes once flagged?"],
        "sprint1_goal": "Confirmed domain, file-level blueprint for Sprint 002.",
        "sprint1_acceptance": ["DOMAIN.md is written in client terminology"],
        "sprint1_inspect": ["samples/rebate-q3.xlsx"],
        "state_current": "Sprint 001 — interview complete, planning files populated.",
        "state_next": "Architect review of DOMAIN.md.",
        "state_blockers": [],
    }


def test_render_writes_every_file(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    scaffold(target)
    written = render_all(target, _sample_answers())

    # Spot-check a handful that exercise the various renderers.
    assert (target / "AGENTS.md").read_text().startswith("# AGENTS.md")
    assert (target / "CLAUDE.md").is_file()
    assert (target / "CODEX.md").is_file()
    assert (target / "README.md").read_text().startswith("# quarterly-rebates")
    assert "Acme Wholesale" in (target / "AGENTS.md").read_text()
    assert "Acme Wholesale" in (target / "README.md").read_text()
    assert len(written) >= 15


def test_render_propagates_client_terminology(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    scaffold(target)
    render_all(target, _sample_answers())

    domain = (target / "planning/DOMAIN.md").read_text()
    assert "rebate cycle" in domain
    assert "tier A vendor" in domain
    assert "Operations manager" in domain


def test_render_handles_empty_optional_lists(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    scaffold(target)
    answers = {
        "project_name": "minimal",
        "client": "Internal",
        "tagline": "Just enough to populate.",
        "business_goal": "",
        "tech_stack": "TBD",
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
    }
    # Should not raise.
    render_all(target, answers)
    # Empty inputs render the placeholder strings, not 'None' or Python repr.
    domain = (target / "planning/DOMAIN.md").read_text()
    assert "None" not in domain
    assert "[]" not in domain


def test_sprint1_handoff_includes_sprint_folder_placeholder(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    scaffold(target)
    render_all(target, _sample_answers())

    handoff = (target / "planning/sprints/001-discovery-architecture/handoff-prompt.md").read_text()
    assert "[SPRINT_FOLDER]" in handoff
    assert "AGENTS.md" in handoff
