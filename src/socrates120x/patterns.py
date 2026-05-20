"""The `socrates patterns review` subcommand — keep the patterns folder honest.

Patterns rot. Candidates that never get promoted, candidates whose source
project has been deleted, candidates that nobody has ever re-used — all of
those are signals that the compounding promise is not landing. This module
surfaces them so the operator can act.

The naive "is this slug used in any other project?" check is an rgrep across
every markdown file in every build. For a CompanyOS with 200 projects that
gets expensive. We cache the grep result at `patterns/.usage-cache.json`
and invalidate via mtime: if no input file has changed since the cache was
written, the cached usage map is reused. Pass ``use_cache=False`` to force
a full rescan.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

STALE_CANDIDATE_DAYS = 90
USAGE_CACHE_FILENAME = ".usage-cache.json"
USAGE_CACHE_VERSION = 2


class FindingKind(Enum):
    STALE = "stale-candidate"
    ORPHAN = "orphan-source"
    UNUSED = "unused"


@dataclass(frozen=True)
class PatternFinding:
    kind: FindingKind
    path: Path
    message: str


@dataclass
class PatternReport:
    patterns_dir: Path
    findings: list[PatternFinding]
    candidates_total: int
    promoted_total: int


def review_patterns(companyos_root: Path, *, use_cache: bool = True) -> PatternReport:
    """Inspect *companyos_root*/patterns/ and report drift.

    ``use_cache=True`` (the default) reads ``patterns/.usage-cache.json`` and
    reuses any **per-project segment** whose tracked mtime hasn't changed.
    Adding/removing a pattern invalidates the slug-set check and forces a
    re-grep per project; changing a file in project P only invalidates P.
    Pass ``use_cache=False`` to drop the cache entirely for one run.
    """
    patterns_dir = companyos_root / "patterns"
    findings: list[PatternFinding] = []
    candidates = 0
    promoted = 0

    if not patterns_dir.is_dir():
        return PatternReport(patterns_dir, findings, 0, 0)

    builds_dir = companyos_root / "builds"
    if builds_dir.is_dir():
        build_names: set[str] | None = {p.name for p in builds_dir.iterdir() if p.is_dir()}
    else:
        build_names = None

    pattern_files = sorted(p for p in patterns_dir.glob("*.md") if p.name != "README.md")
    cache = _load_usage_cache(patterns_dir) if use_cache else None
    usage_map = _compute_usage_map(pattern_files, builds_dir, build_names, cache=cache)

    today = _dt.date.today()
    for pattern in pattern_files:
        is_candidate = pattern.name.startswith("CANDIDATE-")
        if is_candidate:
            candidates += 1
        else:
            promoted += 1
        body = pattern.read_text(errors="replace")
        source = _extract_source_project(body)
        extracted = _extract_extracted_date(body)

        # Stale candidate check.
        if is_candidate and extracted is not None:
            age = (today - extracted).days
            if age > STALE_CANDIDATE_DAYS:
                findings.append(PatternFinding(
                    kind=FindingKind.STALE,
                    path=pattern,
                    message=(
                        f"candidate is {age} days old (threshold {STALE_CANDIDATE_DAYS}d) — "
                        f"promote it or delete it"
                    ),
                ))

        # Orphan source check.
        if source and build_names is not None and source not in build_names:
            findings.append(PatternFinding(
                kind=FindingKind.ORPHAN,
                path=pattern,
                message=(
                    f"source project '{source}' no longer exists in builds/ — "
                    f"the pattern's provenance is broken"
                ),
            ))

        # Unused check via the (possibly cached) usage_map.
        if build_names and len(build_names - {source} if source else build_names) > 0:
            slug = _pattern_slug(pattern.name)
            if slug:
                used_in = usage_map.get(slug, [])
                # Exclude the source project from the use list.
                used_outside = [p for p in used_in if p != source]
                if not used_outside:
                    findings.append(PatternFinding(
                        kind=FindingKind.UNUSED,
                        path=pattern,
                        message=(
                            f"slug '{slug}' is not referenced in any project outside "
                            f"its source — pattern has not yet compounded"
                        ),
                    ))
    return PatternReport(
        patterns_dir=patterns_dir,
        findings=findings,
        candidates_total=candidates,
        promoted_total=promoted,
    )


# ---------------------------------------------------------------------------
# Usage cache (per-project segments, v2)
#
# Schema:
#   {
#     "version": 2,
#     "computed_at": "ISO-8601",
#     "slug_set": ["validate-numbers", "ingest-pipeline", ...],
#     "projects": {
#       "alpha": {"mtime": 1620000000.0, "matched_slugs": ["validate-numbers"]},
#       "beta":  {"mtime": 1620100000.0, "matched_slugs": []}
#     }
#   }
#
# Per-project segment reuse: if a project's tracked mtime equals the live max
# mtime of its *.md files, that project's matched_slugs are reused verbatim.
# Otherwise we re-grep that project against the current slug_set. Adding or
# removing a pattern changes the slug_set, which forces every per-project
# segment to recompute (cheaper than re-grepping nothing would be wrong; the
# alternative — diffing slugs — is deferred until anyone hits the limit).
# ---------------------------------------------------------------------------


def _compute_usage_map(
    pattern_files: list[Path],
    builds_dir: Path,
    build_names: set[str] | None,
    *,
    cache: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Return slug -> [project, ...]; updates and persists the cache as a side effect."""
    if not build_names:
        return {}

    current_slugs = sorted({s for p in pattern_files if (s := _pattern_slug(p.name))})
    cached_slug_set = cache.get("slug_set") if cache else None
    slug_set_unchanged = cached_slug_set == current_slugs

    cached_projects = cache.get("projects", {}) if cache else {}

    new_projects: dict[str, dict[str, Any]] = {}
    for name in sorted(build_names):
        project_dir = builds_dir / name
        live_mtime = _project_mtime(project_dir)
        cached_proj = cached_projects.get(name)
        if (
            slug_set_unchanged
            and cached_proj is not None
            and _approx_eq(cached_proj.get("mtime"), live_mtime)
            and isinstance(cached_proj.get("matched_slugs"), list)
        ):
            matched = [str(s) for s in cached_proj["matched_slugs"] if isinstance(s, str)]
        else:
            matched = [s for s in current_slugs if _slug_in_project(s, project_dir)]
        new_projects[name] = {"mtime": live_mtime, "matched_slugs": matched}

    # Persist the refreshed cache.
    payload = {
        "version": USAGE_CACHE_VERSION,
        "computed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "slug_set": current_slugs,
        "projects": new_projects,
    }
    _save_usage_cache(pattern_files[0].parent if pattern_files else builds_dir.parent / "patterns", payload)

    # Invert: slug -> list of projects mentioning it.
    inverted: dict[str, list[str]] = {slug: [] for slug in current_slugs}
    for proj_name, info in new_projects.items():
        for slug in info["matched_slugs"]:
            if slug in inverted:
                inverted[slug].append(proj_name)
    return inverted


def _slug_in_project(slug: str, project_dir: Path) -> bool:
    needle = slug.lower()
    for f in project_dir.rglob("*.md"):
        try:
            text = f.read_text(errors="replace").lower()
        except OSError:
            continue
        if needle in text:
            return True
    return False


def _project_mtime(project_dir: Path) -> float:
    max_mtime = 0.0
    for f in project_dir.rglob("*.md"):
        try:
            max_mtime = max(max_mtime, f.stat().st_mtime)
        except OSError:
            continue
    return max_mtime


def _approx_eq(a: object, b: float) -> bool:
    """mtime equality with a tiny tolerance — JSON round-trip can shave fractions."""
    if not isinstance(a, (int, float)):
        return False
    return abs(float(a) - b) < 0.001


def _load_usage_cache(patterns_dir: Path) -> dict[str, Any] | None:
    cache_path = patterns_dir / USAGE_CACHE_FILENAME
    if not cache_path.is_file():
        return None
    try:
        data = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != USAGE_CACHE_VERSION:
        return None
    if not isinstance(data.get("projects"), dict):
        return None
    return data


def _save_usage_cache(patterns_dir: Path, payload: dict[str, Any]) -> None:
    """Persist the usage cache atomically.

    `socrates patterns review` on a CompanyOS with many projects can take
    seconds. A SIGINT mid-write would leave a truncated/invalid cache
    file, which would then crash the next run inside json.loads. Use a
    same-directory tempfile + os.replace for atomicity (same pattern as
    interview.py's atomic save) so the cache is either fully old or
    fully new — never half-written.
    """
    if not patterns_dir.is_dir():
        return
    target = patterns_dir / USAGE_CACHE_FILENAME
    tmp = target.with_name(target.name + ".tmp")
    try:
        with contextlib.suppress(OSError):
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def format_pattern_report(report: PatternReport, *, use_color: bool | None = None) -> str:
    if use_color is None:
        use_color = sys.stdout.isatty()
    lines: list[str] = []
    lines.append(f"socrates patterns review — {report.patterns_dir}")
    lines.append(
        f"  {report.candidates_total} candidate(s), "
        f"{report.promoted_total} promoted, "
        f"{len(report.findings)} finding(s)"
    )
    lines.append("")
    if not report.findings:
        lines.append("✓ no findings — patterns layer looks healthy")
        return "\n".join(lines)

    by_kind: dict[FindingKind, list[PatternFinding]] = {k: [] for k in FindingKind}
    for f in report.findings:
        by_kind[f.kind].append(f)

    for kind in FindingKind:
        bucket = by_kind[kind]
        if not bucket:
            continue
        lines.append(f"── {kind.value} ── ({len(bucket)})")
        for f in bucket:
            try:
                rel = f.path.relative_to(report.patterns_dir.parent)
            except ValueError:
                rel = f.path
            lines.append(f"  {rel}: {f.message}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_SOURCE_LINE = re.compile(r"\*\*Source project\*\*\s*\|\s*`([^`]+)`")
_EXTRACTED_LINE = re.compile(r"\*\*Extracted\*\*\s*\|\s*(\d{4})-(\d{2})-(\d{2})")


def _extract_source_project(body: str) -> str | None:
    m = _SOURCE_LINE.search(body)
    return m.group(1) if m else None


def _extract_extracted_date(body: str) -> _dt.date | None:
    m = _EXTRACTED_LINE.search(body)
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _pattern_slug(filename: str) -> str:
    name = filename.removeprefix("CANDIDATE-").removesuffix(".md")
    return name.strip()


