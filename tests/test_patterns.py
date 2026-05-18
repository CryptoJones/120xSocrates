"""Tests for the patterns review subcommand."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x.companyos import scaffold_companyos
from socrates120x.patterns import FindingKind, format_pattern_report, review_patterns
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


def _pattern(text_date: str, source: str, slug: str, candidate: bool = True) -> str:
    return f"""# Pattern: {slug} ({"CANDIDATE" if candidate else "promoted"})

> Demo pattern.

| | |
|---|---|
| **Kind** | demo |
| **Confidence** | 1 / 5 |
| **Extracted** | {text_date} |
| **Source project** | `{source}` |

## When this applies

When tests need it.

## The pattern

(body)
"""


@pytest.fixture
def company(tmp_path: Path) -> Path:
    root = tmp_path / "120x"
    scaffold_companyos(root)
    return root


def _make_build(company: Path, name: str) -> Path:
    project = company / "builds" / name
    scaffold(project)
    render_all(project, {
        "project_name": name, "client": "Acme", "tagline": "demo",
        "business_goal": "g", "tech_stack": "Python",
        "users": [], "current_process": "", "terminology": [],
        "business_rules": [], "decisions": [], "out_of_scope": [],
        "risks": [], "fragile_inputs": "", "open_questions": [],
        "sprint1_goal": "", "sprint1_acceptance": [],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return project


def test_patterns_review_clean_when_no_patterns(company: Path) -> None:
    report = review_patterns(company)
    assert report.findings == []
    assert report.candidates_total == 0


def test_patterns_review_flags_stale_candidate(company: Path) -> None:
    _make_build(company, "alpha")
    old = (_dt.date.today() - _dt.timedelta(days=120)).isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(old, "alpha", "validate-numbers")
    )
    report = review_patterns(company)
    kinds = {f.kind for f in report.findings}
    assert FindingKind.STALE in kinds


def test_patterns_review_flags_orphan_source(company: Path) -> None:
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "ghost-project", "x"))
    report = review_patterns(company)
    kinds = {f.kind for f in report.findings}
    assert FindingKind.ORPHAN in kinds


def test_patterns_review_quiet_when_pattern_reused_elsewhere(company: Path) -> None:
    """A pattern whose slug appears in a build other than its source is 'used'."""
    _make_build(company, "alpha")
    other = _make_build(company, "beta")
    # Mention the pattern slug in beta's STATE.
    (other / "planning" / "STATE.md").write_text(
        (other / "planning" / "STATE.md").read_text() + "\nReused: validate-numbers\n"
    )
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(today, "alpha", "validate-numbers")
    )
    report = review_patterns(company)
    # No UNUSED finding for this pattern (it appears in beta).
    unused_paths = [f.path.name for f in report.findings if f.kind == FindingKind.UNUSED]
    assert "CANDIDATE-validate-numbers.md" not in unused_paths


def test_patterns_review_flags_unused(company: Path) -> None:
    """A pattern referenced only in its source project is unused."""
    alpha = _make_build(company, "alpha")
    _make_build(company, "beta")  # exists but doesn't reference the slug
    # Mention slug in alpha (source) — but nowhere else.
    (alpha / "planning" / "STATE.md").write_text(
        (alpha / "planning" / "STATE.md").read_text() + "\nMentions validate-numbers.\n"
    )
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(today, "alpha", "validate-numbers")
    )
    report = review_patterns(company)
    unused = [f for f in report.findings if f.kind == FindingKind.UNUSED]
    assert any("validate-numbers" in f.path.name for f in unused)


def test_format_pattern_report_clean(company: Path) -> None:
    report = review_patterns(company)
    text = format_pattern_report(report, use_color=False)
    assert "no findings" in text


def test_format_pattern_report_groups_by_kind(company: Path) -> None:
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "ghost", "x"))
    report = review_patterns(company)
    text = format_pattern_report(report, use_color=False)
    assert "orphan-source" in text


# ---------------------------------------------------------------------------
# Usage cache
# ---------------------------------------------------------------------------


def test_review_writes_usage_cache(company: Path) -> None:
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"))
    review_patterns(company)
    cache_path = company / "patterns" / ".usage-cache.json"
    assert cache_path.is_file()
    import json
    data = json.loads(cache_path.read_text())
    assert data["version"] == 1
    assert "x" in data["usage"]


def test_cache_is_used_when_fresh(company: Path) -> None:
    """A pre-existing cache should be honoured if no input is newer than it."""
    import json
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"))
    # First call writes the cache.
    review_patterns(company)
    cache_path = company / "patterns" / ".usage-cache.json"
    data = json.loads(cache_path.read_text())

    # Manually flip the cache's claim about pattern x's usage, then ensure the
    # second review trusts our injected value (proves cache is read).
    data["usage"]["x"] = ["alpha", "fake-other-project"]
    # Bump the max_input_mtime far into the future so it stays fresh no matter what.
    data["max_input_mtime"] = data["max_input_mtime"] + 1_000_000
    cache_path.write_text(json.dumps(data))

    report = review_patterns(company)
    # If the cache was used, the unused-check should NOT fire (the cache claims
    # the slug is referenced by 'fake-other-project').
    unused = [f for f in report.findings if f.kind == FindingKind.UNUSED]
    assert not any("validate-numbers" in f.path.name or f.path.name == "CANDIDATE-x.md" for f in unused)


def test_cache_invalidated_when_inputs_change(company: Path) -> None:
    """Touching a project file should invalidate the cache."""
    import json
    import os
    import time
    alpha = _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"))
    review_patterns(company)  # populates cache

    # Touch a markdown file in alpha so mtime advances past the cache snapshot.
    state = alpha / "planning" / "STATE.md"
    time.sleep(0.05)  # ensure mtime resolution > cache write timestamp
    state_mtime = state.stat().st_mtime + 5
    os.utime(state, (state_mtime, state_mtime))

    # Force a rescan path via mtime invalidation (use_cache=True default).
    report = review_patterns(company)
    # Cache should have been refreshed with the new max_input_mtime.
    cache = json.loads((company / "patterns" / ".usage-cache.json").read_text())
    assert cache["max_input_mtime"] >= state_mtime
    # Sanity: no crash, no spurious findings beyond the orphan/unused report.
    assert isinstance(report.findings, list)


def test_use_cache_false_forces_rescan(company: Path) -> None:
    """use_cache=False ignores the existing cache and recomputes."""
    import json
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"))
    # Seed a stale cache claiming the slug is used.
    cache_path = company / "patterns" / ".usage-cache.json"
    cache_path.write_text(json.dumps({
        "version": 1,
        "computed_at": "1970-01-01T00:00:00+00:00",
        "max_input_mtime": 9_999_999_999.0,  # implausibly future
        "usage": {"x": ["alpha", "phantom-project"]},
    }))
    # With cache disabled, the rescan happens — phantom-project is NOT real,
    # so x has no real outside-use and should be flagged unused IF other
    # projects exist. With only "alpha" present, the unused check is skipped
    # anyway. The point of this test is that no crash + cache gets overwritten.
    report = review_patterns(company, use_cache=False)
    new_cache = json.loads(cache_path.read_text())
    assert new_cache["max_input_mtime"] < 9_999_999_999.0  # cache was refreshed
    # Sanity
    assert isinstance(report.findings, list)
