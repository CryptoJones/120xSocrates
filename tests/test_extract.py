"""Tests for the extract subcommand."""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x.companyos import scaffold_companyos
from socrates120x.extract import _resolve_patterns_dir, _sanitize_slug, render_pattern
from socrates120x.scaffold import scaffold


def test_sanitize_slug_cleans_input() -> None:
    assert _sanitize_slug("Validate Parsed Numbers") == "validate-parsed-numbers"
    assert _sanitize_slug("  --validate--parsed--numbers  ") == "validate-parsed-numbers"
    assert _sanitize_slug("ALL CAPS!!! 123") == "all-caps-123"
    assert _sanitize_slug("") == "untitled"
    assert _sanitize_slug("$$$") == "untitled"


def test_resolve_patterns_dir_finds_companyos_sibling(tmp_path: Path) -> None:
    company = tmp_path / "120x"
    scaffold_companyos(company)
    project = company / "builds" / "demo"
    scaffold(project)

    resolved = _resolve_patterns_dir(project)
    assert resolved == company / "patterns"


def test_resolve_patterns_dir_falls_back_to_local(tmp_path: Path) -> None:
    project = tmp_path / "standalone"
    scaffold(project)

    resolved = _resolve_patterns_dir(project)
    assert resolved == project / "patterns"


def test_render_pattern_includes_all_sections() -> None:
    answers = {
        "pattern_slug": "validate-parsed-numbers",
        "pattern_kind": "validation-approach",
        "pattern_confidence": "2",
        "pattern_summary": "Cross-check parsed values against source totals.",
        "pattern_when_applies": "When ingesting spreadsheets with subtotal rows.",
        "pattern_when_does_not": "When the source has no subtotals.",
        "pattern_body": "def validate(parsed, source_total):\n    assert sum(parsed) == source_total",
        "pattern_war_story": "We shipped wrong rebate numbers in Q2 and got caught by the client.",
        "pattern_focus": "The validation step that caught the Q2 bug.",
    }
    body = render_pattern(answers, project=Path("/tmp/demo"))
    assert "CANDIDATE" in body
    assert "validate-parsed-numbers" in body
    assert "2 / 5" in body
    assert "Cross-check parsed values" in body
    assert "def validate" in body
    assert "war story" in body.lower()
    assert "demo" in body  # project name


@pytest.mark.parametrize("missing_key", [
    "pattern_summary", "pattern_kind", "pattern_when_applies",
    "pattern_when_does_not", "pattern_body", "pattern_war_story",
])
def test_render_pattern_handles_missing_field(missing_key: str) -> None:
    answers = {
        "pattern_slug": "x",
        "pattern_summary": "summary",
        "pattern_kind": "kind",
        "pattern_when_applies": "applies",
        "pattern_when_does_not": "does not",
        "pattern_body": "body",
        "pattern_war_story": "story",
        "pattern_focus": "focus",
        "pattern_confidence": "1",
    }
    del answers[missing_key]
    body = render_pattern(answers, project=Path("/tmp/demo"))
    # Renderer should not crash and should produce some content for the missing field.
    assert "_(" in body  # placeholder text appears
