"""Tests for socrates pack."""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x.pack import build_pack, write_pack
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "AcmeCorp", "tagline": "demo tagline",
        "business_goal": "the goal", "tech_stack": "Python + DuckDB",
        "users": ["op"], "current_process": "manual", "terminology": [],
        "business_rules": [], "decisions": ["choice — reason"], "out_of_scope": [],
        "risks": ["risk one"], "fragile_inputs": "", "open_questions": ["q1?"],
        "sprint1_goal": "", "sprint1_acceptance": ["criterion one"],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return p


def test_pack_contains_every_planning_file(project: Path) -> None:
    text = build_pack(project)
    assert "AGENTS.md" in text
    assert "STATE.md" in text
    assert "DOMAIN.md" in text
    assert "DECISIONS.md" in text
    assert "RISKS.md" in text
    assert "QUESTIONS.md" in text
    assert "requirements.md" in text
    assert "blueprint.md" in text
    assert "acceptance.md" in text
    assert "handoff-prompt.md" in text


def test_pack_includes_client_terminology(project: Path) -> None:
    text = build_pack(project)
    assert "AcmeCorp" in text
    assert "choice — reason" in text
    assert "risk one" in text
    assert "q1?" in text


def test_pack_targets_active_sprint(project: Path) -> None:
    text = build_pack(project)
    assert "001-discovery-architecture" in text


def test_pack_specific_sprint(project: Path) -> None:
    # Create a sprint 002 folder with stub files.
    sprint2 = project / "planning" / "sprints" / "002-rebate-engine"
    sprint2.mkdir()
    for fname in ("requirements.md", "blueprint.md", "acceptance.md", "handoff-prompt.md"):
        (sprint2 / fname).write_text(f"# {fname} (sprint 2)")
    text = build_pack(project, include_sprint="002-rebate-engine")
    assert "002-rebate-engine" in text
    # Sprint 1 files should NOT appear since we asked for sprint 2.
    assert "001-discovery-architecture" not in text


def test_pack_handles_missing_file_gracefully(project: Path) -> None:
    (project / "planning" / "STATE.md").unlink()
    text = build_pack(project)
    assert "file not present — skipped" in text


def test_write_pack_creates_file(project: Path) -> None:
    target = write_pack(project)
    assert target == project / ".socrates-architect-pack.md"
    assert target.is_file()
    assert "AcmeCorp" in target.read_text()


def test_pack_starts_with_architect_header(project: Path) -> None:
    text = build_pack(project)
    assert text.startswith("# Architect input bundle")
    assert "Paste this entire file" in text
