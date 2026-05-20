"""Tests for the audit subsystem.

Each check gets a clean-project case (no findings) and a broken-project case
(specific findings). The clean fixture is produced by scaffolding + rendering
with realistic answers, the same path a normal `socrates init` run produces.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from socrates120x.audit import format_report, run_audit
from socrates120x.audit.checks import (
    AdapterPointsToAgentsCheck,
    AlwaysOnRisksCheck,
    RequiredFilesCheck,
    ScaffoldShapeCheck,
    SprintFolderCheck,
    StateFreshnessCheck,
    TerminologyUsedCheck,
    WeaselWordsCheck,
)
from socrates120x.audit.model import Severity
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
        "current_process": "Analysts open vendor sheets and copy values manually.",
        "terminology": [
            "rebate cycle — quarterly window when payouts are calculated",
            "tier A vendor — pre-approved supplier",
        ],
        "business_rules": ["Money is stored in integer cents"],
        "decisions": ["Supabase over self-hosted — client already has an account"],
        "out_of_scope": ["Mobile app"],
        "risks": ["Vendor sheets change column order between quarters"],
        "fragile_inputs": "TMS CSV export schema drifts.",
        "open_questions": ["Who owns rebate disputes?"],
        "sprint1_goal": "Confirmed domain, blueprint for Sprint 002.",
        "sprint1_acceptance": [
            "DOMAIN.md is written in client terminology",
            "Sprint 002 folder exists with all four files",
        ],
        "sprint1_inspect": ["samples/rebate-q3.xlsx"],
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


# ---------------------------------------------------------------------------
# End-to-end: a freshly populated project should have NO error-or-warning
# findings (info-level advisories are acceptable).
# ---------------------------------------------------------------------------


def test_freshly_populated_project_has_no_errors(clean_project: Path) -> None:
    report = run_audit(clean_project)
    errors = report.by_severity(Severity.ERROR)
    warnings = report.by_severity(Severity.WARNING)
    assert errors == [], f"unexpected errors on clean project: {errors}"
    assert warnings == [], f"unexpected warnings on clean project: {warnings}"


def test_audit_runs_every_check(clean_project: Path) -> None:
    report = run_audit(clean_project)
    expected = {
        "required-files",
        "scaffold-shape",
        "sprint-folders",
        "adapter-routing",
        "acceptance-weasels",
        "state-freshness",
        "always-on-risks",
        "terminology-used",
    }
    assert set(report.checks_run) == expected


# ---------------------------------------------------------------------------
# Per-check negative cases
# ---------------------------------------------------------------------------


def test_required_files_check_fires_on_missing(clean_project: Path) -> None:
    (clean_project / "planning" / "STATE.md").unlink()
    findings = RequiredFilesCheck().run(clean_project)
    assert any("STATE.md" in f.message for f in findings)
    assert all(f.severity is Severity.ERROR for f in findings)


def test_scaffold_shape_check_emits_info_on_pruning(clean_project: Path) -> None:
    """Pruning is allowed — the check is INFO, not WARNING, to keep audit quiet."""
    (clean_project / "docs" / "API.md").unlink()
    findings = ScaffoldShapeCheck().run(clean_project)
    assert any("API.md" in f.message for f in findings)
    assert all(f.severity is Severity.INFO for f in findings)


def test_scaffold_shape_check_honours_skip_list(clean_project: Path) -> None:
    """`.socrates-audit.json` lets the operator silence specific paths."""
    import json

    (clean_project / "docs" / "API.md").unlink()
    (clean_project / "docs" / "PERMISSIONS.md").unlink()
    (clean_project / ".socrates-audit.json").write_text(
        json.dumps({"scaffold_shape": {"ignore": ["docs/API.md"]}}), encoding="utf-8"
    )
    findings = ScaffoldShapeCheck().run(clean_project)
    messages = [f.message for f in findings]
    # API.md was ignored; PERMISSIONS.md still fires.
    assert not any("API.md" in m for m in messages)
    assert any("PERMISSIONS.md" in m for m in messages)


def test_sprint_folder_check_flags_bad_name(clean_project: Path) -> None:
    bad = clean_project / "planning" / "sprints" / "next-thing"
    bad.mkdir()
    for fname in ("requirements.md", "blueprint.md", "acceptance.md", "handoff-prompt.md"):
        (bad / fname).touch()
    findings = SprintFolderCheck().run(clean_project)
    assert any("next-thing" in f.message and "NNN-slug" in f.message for f in findings)


def test_sprint_folder_check_flags_missing_files(clean_project: Path) -> None:
    sprint = clean_project / "planning" / "sprints" / "002-rebate-engine"
    sprint.mkdir()
    (sprint / "requirements.md").touch()
    findings = SprintFolderCheck().run(clean_project)
    messages = [f.message for f in findings]
    for missing in ("blueprint.md", "acceptance.md", "handoff-prompt.md"):
        assert any(missing in m for m in messages), f"expected {missing} to be flagged"


def test_adapter_check_fires_when_pointer_missing(clean_project: Path) -> None:
    (clean_project / "CLAUDE.md").write_text(
        "# This file does not mention the router.", encoding="utf-8"
    )
    findings = AdapterPointsToAgentsCheck().run(clean_project)
    assert any("CLAUDE.md" in f.message for f in findings)


def test_weasel_words_check_fires(clean_project: Path) -> None:
    acc = clean_project / "planning" / "sprints" / "001-discovery-architecture" / "acceptance.md"
    acc.write_text(
        "# acceptance\n\n"
        "- The system is robust enough for production.\n"
        "- Tests pass as needed.\n"
        "- DOMAIN.md reflects client terminology.\n",  # this line is clean
        encoding="utf-8",
    )
    findings = WeaselWordsCheck().run(clean_project)
    assert len(findings) == 2
    assert {f.line for f in findings} == {3, 4}


def test_state_freshness_check_fires_on_old_date(clean_project: Path) -> None:
    state = clean_project / "planning" / "STATE.md"
    old = (_dt.date.today() - _dt.timedelta(days=120)).isoformat()
    state.write_text(f"# STATE\n\n_Last updated: {old}_\n", encoding="utf-8")
    findings = StateFreshnessCheck().run(clean_project)
    assert len(findings) == 1
    assert "120 days ago" in findings[0].message


def test_state_freshness_check_quiet_when_fresh(clean_project: Path) -> None:
    # The default render writes today's date, so a clean run should be silent.
    findings = StateFreshnessCheck().run(clean_project)
    assert findings == []


def test_always_on_risks_check_fires_when_missing(clean_project: Path) -> None:
    risks = clean_project / "planning" / "RISKS.md"
    risks.write_text("# RISKS\n\n- Some project-specific risk only.\n", encoding="utf-8")
    findings = AlwaysOnRisksCheck().run(clean_project)
    assert len(findings) == 1
    assert "source of truth" in findings[0].message.lower()


def test_terminology_used_check_flags_orphan_term(clean_project: Path) -> None:
    # Rewrite DOMAIN.md so 'orphaned-concept' is defined but used nowhere else,
    # and 'live-term' is defined AND mentioned in RISKS.md.
    domain = clean_project / "planning" / "DOMAIN.md"
    domain.write_text(
        "# DOMAIN\n\n"
        "## Terminology\n\n"
        "- orphaned-concept — a thing nothing else mentions\n"
        "- live-term — referenced elsewhere\n",
        encoding="utf-8",
    )
    risks = clean_project / "planning" / "RISKS.md"
    risks.write_text(
        risks.read_text(encoding="utf-8") + "\n\nNote: a live-term issue could surface here."
    )
    findings = TerminologyUsedCheck().run(clean_project)
    flagged = {f.message for f in findings}
    assert any("orphaned-concept" in m for m in flagged)
    assert not any("live-term" in m for m in flagged)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_text_report_includes_severity_buckets(clean_project: Path) -> None:
    (clean_project / "planning" / "QUESTIONS.md").unlink()
    report = run_audit(clean_project)
    text = format_report(report)
    assert "ERROR" in text
    assert "QUESTIONS.md" in text
    assert "errors" in text


def test_json_report_is_valid_json(clean_project: Path) -> None:
    report = run_audit(clean_project)
    text = format_report(report, as_json=True)
    parsed = json.loads(text)
    assert parsed["project_path"].endswith("demo")
    assert "findings" in parsed
    assert "counts" in parsed


def test_text_report_clean_says_so(clean_project: Path) -> None:
    report = run_audit(clean_project)
    text = format_report(report)
    # A freshly populated project may have INFO findings, but the report
    # should make clear which side it's on.
    if not report.findings:
        assert "no findings" in text
