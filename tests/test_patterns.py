"""Tests for the patterns review subcommand."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from socrates120x import (
    FindingKind,
    format_pattern_report,
    render_all,
    review_patterns,
    scaffold,
    scaffold_companyos,
)


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
    , encoding="utf-8")
    report = review_patterns(company)
    kinds = {f.kind for f in report.findings}
    assert FindingKind.STALE in kinds


def test_patterns_review_flags_orphan_source(company: Path) -> None:
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "ghost-project", "x"), encoding="utf-8")
    report = review_patterns(company)
    kinds = {f.kind for f in report.findings}
    assert FindingKind.ORPHAN in kinds


def test_patterns_review_quiet_when_pattern_reused_elsewhere(company: Path) -> None:
    """A pattern whose slug appears in a build other than its source is 'used'."""
    _make_build(company, "alpha")
    other = _make_build(company, "beta")
    # Mention the pattern slug in beta's STATE.
    (other / "planning" / "STATE.md").write_text(
        (other / "planning" / "STATE.md").read_text(encoding="utf-8") + "\nReused: validate-numbers\n"
    , encoding="utf-8")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(today, "alpha", "validate-numbers")
    , encoding="utf-8")
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
        (alpha / "planning" / "STATE.md").read_text(encoding="utf-8") + "\nMentions validate-numbers.\n"
    , encoding="utf-8")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(today, "alpha", "validate-numbers")
    , encoding="utf-8")
    report = review_patterns(company)
    unused = [f for f in report.findings if f.kind == FindingKind.UNUSED]
    assert any("validate-numbers" in f.path.name for f in unused)


def test_format_pattern_report_clean(company: Path) -> None:
    report = review_patterns(company)
    text = format_pattern_report(report, use_color=False)
    assert "no findings" in text


def test_format_pattern_report_groups_by_kind(company: Path) -> None:
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "ghost", "x"), encoding="utf-8")
    report = review_patterns(company)
    text = format_pattern_report(report, use_color=False)
    assert "orphan-source" in text


# ---------------------------------------------------------------------------
# Usage cache
# ---------------------------------------------------------------------------


def test_review_writes_usage_cache(company: Path) -> None:
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"), encoding="utf-8")
    review_patterns(company)
    cache_path = company / "patterns" / ".usage-cache.json"
    assert cache_path.is_file()
    import json
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert "x" in data["slug_set"]
    assert "alpha" in data["projects"]
    assert isinstance(data["projects"]["alpha"]["matched_slugs"], list)


def test_cache_per_project_segment_is_reused(company: Path) -> None:
    """If a project's mtime is unchanged AND slug_set is unchanged, that
    project's cached matched_slugs is trusted verbatim — including
    fabricated entries we inject for the test."""
    import json
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"), encoding="utf-8")
    review_patterns(company)
    cache_path = company / "patterns" / ".usage-cache.json"
    data = json.loads(cache_path.read_text(encoding="utf-8"))

    # Inject a fake matched slug into alpha's segment WITHOUT changing alpha's mtime.
    data["projects"]["alpha"]["matched_slugs"] = ["x", "phantom-slug"]
    cache_path.write_text(json.dumps(data), encoding="utf-8")

    review_patterns(company)
    refreshed = json.loads(cache_path.read_text(encoding="utf-8"))
    # The injected entry must survive — alpha's segment was reused.
    assert "phantom-slug" in refreshed["projects"]["alpha"]["matched_slugs"]


def test_cache_invalidated_per_project_on_mtime_bump(company: Path) -> None:
    """Touching a file in alpha should re-grep alpha only — and overwrite
    that project's cached matched_slugs."""
    import json
    import os
    import time
    alpha = _make_build(company, "alpha")
    _make_build(company, "beta")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"), encoding="utf-8")
    review_patterns(company)
    cache_path = company / "patterns" / ".usage-cache.json"

    # Inject phantom slugs into BOTH project segments.
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    data["projects"]["alpha"]["matched_slugs"] = ["x", "phantom-from-alpha"]
    data["projects"]["beta"]["matched_slugs"] = ["phantom-from-beta"]
    cache_path.write_text(json.dumps(data), encoding="utf-8")

    # Bump alpha's mtime, leave beta alone.
    state = alpha / "planning" / "STATE.md"
    time.sleep(0.05)
    new_mtime = state.stat().st_mtime + 5
    os.utime(state, (new_mtime, new_mtime))

    review_patterns(company)
    refreshed = json.loads(cache_path.read_text(encoding="utf-8"))
    # alpha was rescanned; phantom entry is gone.
    assert "phantom-from-alpha" not in refreshed["projects"]["alpha"]["matched_slugs"]
    # beta was NOT rescanned; phantom entry survives.
    assert "phantom-from-beta" in refreshed["projects"]["beta"]["matched_slugs"]


def test_cache_invalidated_when_slug_set_changes(company: Path) -> None:
    """Adding a new pattern invalidates every project's segment."""
    import json
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"), encoding="utf-8")
    review_patterns(company)
    cache_path = company / "patterns" / ".usage-cache.json"

    # Inject a phantom slug; will be wiped when the slug_set changes.
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    data["projects"]["alpha"]["matched_slugs"] = ["x", "phantom"]
    cache_path.write_text(json.dumps(data), encoding="utf-8")

    # Add a second pattern. slug_set changes.
    (company / "patterns" / "CANDIDATE-y.md").write_text(_pattern(today, "alpha", "y"), encoding="utf-8")
    review_patterns(company)

    refreshed = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "phantom" not in refreshed["projects"]["alpha"]["matched_slugs"]
    assert set(refreshed["slug_set"]) == {"x", "y"}


def test_use_cache_false_forces_rescan(company: Path) -> None:
    """use_cache=False ignores the existing cache and recomputes."""
    import json
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"), encoding="utf-8")
    cache_path = company / "patterns" / ".usage-cache.json"
    # Seed a stale cache that claims alpha mentions a phantom slug.
    cache_path.write_text(json.dumps({
        "version": 2,
        "computed_at": "1970-01-01T00:00:00+00:00",
        "slug_set": ["x"],
        "projects": {"alpha": {"mtime": 9_999_999_999.0, "matched_slugs": ["x", "phantom"]}},
    }), encoding="utf-8")
    review_patterns(company, use_cache=False)
    refreshed = json.loads(cache_path.read_text(encoding="utf-8"))
    # Cache was overwritten; phantom is gone.
    assert "phantom" not in refreshed["projects"]["alpha"]["matched_slugs"]


def test_cache_rejects_old_version(company: Path) -> None:
    """A v1 cache (from earlier socrates) is treated as missing."""
    import json
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(_pattern(today, "alpha", "x"), encoding="utf-8")
    cache_path = company / "patterns" / ".usage-cache.json"
    cache_path.write_text(json.dumps({
        "version": 1,
        "computed_at": "1970-01-01T00:00:00+00:00",
        "max_input_mtime": 9_999_999_999.0,
        "usage": {"x": ["alpha", "phantom-from-v1"]},
    }), encoding="utf-8")
    review_patterns(company)
    refreshed = json.loads(cache_path.read_text(encoding="utf-8"))
    assert refreshed["version"] == 2
    assert "phantom-from-v1" not in str(refreshed)


def test_patterns_review_no_false_positive_on_short_slug_substring(company: Path) -> None:
    """A pattern slug like `auth` must NOT match `author` in another project.

    Bug: previous naive substring match `auth in author` -> True -> the
    pattern was reported as 'used elsewhere' and never flagged as unused,
    silently masking genuinely unused short-slug patterns.
    """
    alpha = _make_build(company, "alpha")
    beta = _make_build(company, "beta")
    # alpha (source) mentions the slug somewhere — establishes the source.
    (alpha / "planning" / "STATE.md").write_text(
        (alpha / "planning" / "STATE.md").read_text(encoding="utf-8") + "\nThe `auth` pattern.\n"
    , encoding="utf-8")
    # beta mentions `author` (longer word containing `auth`). Pre-fix this
    # would have looked like a usage of the `auth` slug and the pattern
    # would NOT have been flagged unused.
    (beta / "planning" / "STATE.md").write_text(
        (beta / "planning" / "STATE.md").read_text(encoding="utf-8")
        + "\nThe author of this is unknown.\n"
    , encoding="utf-8")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-auth.md").write_text(
        _pattern(today, "alpha", "auth")
    , encoding="utf-8")
    report = review_patterns(company)
    unused = [f for f in report.findings if f.kind == FindingKind.UNUSED]
    # The pattern IS unused; substring-into-`author` should not save it.
    assert any("auth" in f.path.name for f in unused), (
        "regression: short slug 'auth' was matched as a substring of 'author'"
    )


def test_patterns_review_no_false_positive_on_kebab_subset(company: Path) -> None:
    """A pattern slug `validate-numbers` must NOT match `validate-numbers-attempt`
    (a longer kebab-case identifier that happens to start with the slug).
    """
    alpha = _make_build(company, "alpha")
    beta = _make_build(company, "beta")
    (alpha / "planning" / "STATE.md").write_text(
        (alpha / "planning" / "STATE.md").read_text(encoding="utf-8")
        + "\nThe `validate-numbers` pattern was extracted here.\n"
    , encoding="utf-8")
    # beta has a DIFFERENT kebab identifier that contains the slug as a prefix.
    (beta / "planning" / "STATE.md").write_text(
        (beta / "planning" / "STATE.md").read_text(encoding="utf-8")
        + "\nWe tried validate-numbers-attempt instead, see #42.\n"
    , encoding="utf-8")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(today, "alpha", "validate-numbers")
    , encoding="utf-8")
    report = review_patterns(company)
    unused = [f for f in report.findings if f.kind == FindingKind.UNUSED]
    assert any("validate-numbers" in f.path.name for f in unused), (
        "regression: kebab slug matched as prefix of a longer kebab identifier"
    )


def test_patterns_review_still_matches_exact_kebab_slug(company: Path) -> None:
    """Positive control: an exact slug mention in another project still counts."""
    alpha = _make_build(company, "alpha")
    beta = _make_build(company, "beta")
    (alpha / "planning" / "STATE.md").write_text(
        (alpha / "planning" / "STATE.md").read_text(encoding="utf-8") + "\nThe `validate-numbers` pattern.\n"
    , encoding="utf-8")
    (beta / "planning" / "STATE.md").write_text(
        (beta / "planning" / "STATE.md").read_text(encoding="utf-8")
        + "\nWe reused validate-numbers from alpha.\n"
    , encoding="utf-8")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-validate-numbers.md").write_text(
        _pattern(today, "alpha", "validate-numbers")
    , encoding="utf-8")
    report = review_patterns(company)
    unused_paths = [f.path.name for f in report.findings if f.kind == FindingKind.UNUSED]
    assert "CANDIDATE-validate-numbers.md" not in unused_paths

# ---------------------------------------------------------------------------
# Atomic cache save (reliability/patterns-cache-atomic-save)
# ---------------------------------------------------------------------------


def test_usage_cache_save_is_atomic_no_tempfile_left(company) -> None:
    """After a successful run, no .tmp leftover next to the cache."""
    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(
        _pattern(today, "alpha", "x"), encoding="utf-8",
    )
    review_patterns(company)  # writes the cache
    cache = company / "patterns" / ".usage-cache.json"
    assert cache.is_file()
    assert not (company / "patterns" / ".usage-cache.json.tmp").exists()


def test_usage_cache_save_does_not_clobber_on_failure(
    company, monkeypatch
) -> None:
    """If os.replace fails mid-save, the pre-existing cache must not be
    truncated/wiped — atomic-write contract."""
    import socrates120x as patterns_mod

    _make_build(company, "alpha")
    today = _dt.date.today().isoformat()
    (company / "patterns" / "CANDIDATE-x.md").write_text(
        _pattern(today, "alpha", "x"), encoding="utf-8",
    )
    # First run writes a real cache.
    review_patterns(company)
    cache = company / "patterns" / ".usage-cache.json"
    original = cache.read_text(encoding="utf-8")

    # Now patch os.replace to fail and re-run — original cache must survive.
    def boom(src, dst):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(patterns_mod.os, "replace", boom)
    # Touch a build .md file so the cache would have been rewritten.
    state = company / "builds" / "alpha" / "planning" / "STATE.md"
    state.write_text(state.read_text(encoding="utf-8") + "\nedit\n", encoding="utf-8")
    review_patterns(company)  # must not raise; failed save is swallowed

    # Pre-existing cache is untouched (or has been replaced atomically by
    # earlier successful writes — but never truncated/empty).
    survived = cache.read_text(encoding="utf-8")
    assert survived == original
    # No stranded tempfile.
    assert not (company / "patterns" / ".usage-cache.json.tmp").exists()
