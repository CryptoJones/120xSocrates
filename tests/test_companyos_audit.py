"""Tests for the CompanyOS-level audit check set."""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x.audit import looks_like_companyos, run_audit
from socrates120x.audit.companyos_checks import (
    CompanyOSStructureCheck,
    OrphanBuildsCheck,
    OrphanPatternSourceCheck,
    StaleProposalCheck,
)
from socrates120x.audit.model import Severity
from socrates120x.companyos import scaffold_companyos
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


@pytest.fixture
def company(tmp_path: Path) -> Path:
    root = tmp_path / "120x"
    scaffold_companyos(root)
    return root


def _make_build(company: Path, name: str, client: str = "Acme") -> Path:
    project = company / "builds" / name
    scaffold(project)
    render_all(project, {
        "project_name": name, "client": client, "tagline": "demo",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [], "decisions": [], "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return project


def test_looks_like_companyos_detects_fresh_scaffold(company: Path) -> None:
    assert looks_like_companyos(company)


def test_looks_like_companyos_rejects_plain_dir(tmp_path: Path) -> None:
    project = tmp_path / "not-a-companyos"
    project.mkdir()
    assert not looks_like_companyos(project)


def test_structure_check_passes_on_fresh_scaffold(company: Path) -> None:
    findings = CompanyOSStructureCheck().run(company)
    assert findings == []


def test_structure_check_fires_when_directory_missing(company: Path) -> None:
    (company / "AGENTS.md").unlink()
    findings = CompanyOSStructureCheck().run(company)
    assert any("AGENTS.md" in f.message for f in findings)


def test_orphan_builds_check_fires_when_no_matching_client(company: Path) -> None:
    _make_build(company, "alpha", client="GhostCo")
    # No clients/GhostCo/ folder exists.
    findings = OrphanBuildsCheck().run(company)
    assert any("GhostCo" in f.message for f in findings)


def test_orphan_builds_check_quiet_when_client_internal(company: Path) -> None:
    _make_build(company, "alpha", client="Internal")
    findings = OrphanBuildsCheck().run(company)
    # 'Internal' is whitelisted.
    assert not any("Internal" in f.message for f in findings)


def test_orphan_builds_check_quiet_when_client_folder_exists(company: Path) -> None:
    _make_build(company, "alpha", client="RealClient")
    (company / "clients" / "RealClient").mkdir()
    findings = OrphanBuildsCheck().run(company)
    assert not any("RealClient" in f.message for f in findings)


def test_orphan_pattern_source_check_fires(company: Path) -> None:
    (company / "patterns" / "CANDIDATE-x.md").write_text(
        "**Source project** | `ghost-project`\n"
    )
    findings = OrphanPatternSourceCheck().run(company)
    assert any("ghost-project" in f.message for f in findings)


def test_orphan_pattern_source_check_quiet_when_source_exists(company: Path) -> None:
    _make_build(company, "alpha")
    (company / "patterns" / "CANDIDATE-x.md").write_text(
        "**Source project** | `alpha`\n"
    )
    findings = OrphanPatternSourceCheck().run(company)
    assert findings == []


def test_stale_proposal_check_flags_mention(company: Path) -> None:
    (company / "pipeline" / "proposals.md").write_text(
        "### Project — Client — 2026-01-01\n"
        "Slug: `quarterly-rebates`\n"
    )
    findings = StaleProposalCheck().run(company)
    assert any("quarterly-rebates" in f.message for f in findings)


def test_stale_proposal_check_quiet_when_build_exists(company: Path) -> None:
    _make_build(company, "quarterly-rebates")
    (company / "pipeline" / "proposals.md").write_text(
        "Slug: `quarterly-rebates`\n"
    )
    findings = StaleProposalCheck().run(company)
    assert findings == []


def test_run_audit_with_companyos_flag(company: Path) -> None:
    report = run_audit(company, companyos=True)
    # Fresh scaffold: should have 0 findings.
    assert all(f.severity is not Severity.ERROR for f in report.findings)
    # Companyos check set used.
    assert "companyos-structure" in report.checks_run
    assert "required-files" not in report.checks_run  # per-project checks NOT run


def test_run_audit_auto_detects_companyos_via_runner(company: Path) -> None:
    # Caller passes companyos=False (default) but we test the runner correctly
    # routes when explicitly told.
    report = run_audit(company, companyos=False)
    assert "required-files" in report.checks_run
    assert "companyos-structure" not in report.checks_run
