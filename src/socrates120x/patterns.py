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
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

STALE_CANDIDATE_DAYS = 90
USAGE_CACHE_FILENAME = ".usage-cache.json"
USAGE_CACHE_VERSION = 1


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

    ``use_cache=True`` (the default) reads ``patterns/.usage-cache.json`` if
    fresh (no input file mtime exceeds the cache snapshot) and uses its
    pre-computed usage map. ``use_cache=False`` forces a full rescan; the
    cache is still written.
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

    # Try to use the cached usage map.
    usage_map: dict[str, list[str]] | None = None
    if use_cache:
        usage_map = _load_usage_cache(patterns_dir, builds_dir)

    if usage_map is None:
        # Recompute from scratch and persist.
        usage_map = _compute_usage_map(pattern_files, builds_dir, build_names)
        _save_usage_cache(patterns_dir, builds_dir, usage_map)

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
# Usage cache
# ---------------------------------------------------------------------------


def _compute_usage_map(
    pattern_files: list[Path],
    builds_dir: Path,
    build_names: set[str] | None,
) -> dict[str, list[str]]:
    """Grep every build for every pattern slug; return slug -> [project, ...]."""
    if not build_names:
        return {}
    result: dict[str, list[str]] = {}
    for pattern in pattern_files:
        slug = _pattern_slug(pattern.name)
        if not slug:
            continue
        result[slug] = _projects_mentioning(slug, builds_dir, build_names)
    return result


def _projects_mentioning(slug: str, builds_dir: Path, build_names: set[str]) -> list[str]:
    needle = slug.lower()
    hits: list[str] = []
    for name in sorted(build_names):
        project = builds_dir / name
        for f in project.rglob("*.md"):
            try:
                text = f.read_text(errors="replace").lower()
            except OSError:
                continue
            if needle in text:
                hits.append(name)
                break
    return hits


def _load_usage_cache(patterns_dir: Path, builds_dir: Path) -> dict[str, list[str]] | None:
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
    cached_mtime = data.get("max_input_mtime")
    if not isinstance(cached_mtime, (int, float)):
        return None
    current_mtime = _max_input_mtime(patterns_dir, builds_dir)
    if current_mtime > cached_mtime:
        return None  # cache stale
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    # Coerce values to list[str] defensively.
    out: dict[str, list[str]] = {}
    for slug, names in usage.items():
        if isinstance(names, list):
            out[str(slug)] = [str(n) for n in names if isinstance(n, str)]
    return out


def _save_usage_cache(
    patterns_dir: Path,
    builds_dir: Path,
    usage_map: dict[str, list[str]],
) -> None:
    payload = {
        "version": USAGE_CACHE_VERSION,
        "computed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "max_input_mtime": _max_input_mtime(patterns_dir, builds_dir),
        "usage": usage_map,
    }
    with contextlib.suppress(OSError):
        (patterns_dir / USAGE_CACHE_FILENAME).write_text(json.dumps(payload, indent=2))


def _max_input_mtime(patterns_dir: Path, builds_dir: Path) -> float:
    """Largest mtime across every input that could affect the usage map."""
    max_mtime = 0.0
    for p in patterns_dir.glob("*.md"):
        try:
            max_mtime = max(max_mtime, p.stat().st_mtime)
        except OSError:
            continue
    if builds_dir.is_dir():
        for p in builds_dir.rglob("*.md"):
            try:
                max_mtime = max(max_mtime, p.stat().st_mtime)
            except OSError:
                continue
    return max_mtime


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


