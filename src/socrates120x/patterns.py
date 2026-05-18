"""The `socrates patterns review` subcommand — keep the patterns folder honest.

Patterns rot. Candidates that never get promoted, candidates whose source
project has been deleted, candidates that nobody has ever re-used — all of
those are signals that the compounding promise is not landing. This module
surfaces them so the operator can act.
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

STALE_CANDIDATE_DAYS = 90


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


def review_patterns(companyos_root: Path) -> PatternReport:
    """Inspect *companyos_root*/patterns/ and report drift."""
    patterns_dir = companyos_root / "patterns"
    findings: list[PatternFinding] = []
    candidates = 0
    promoted = 0

    if not patterns_dir.is_dir():
        return PatternReport(patterns_dir, findings, 0, 0)

    builds_dir = companyos_root / "builds"
    # Distinguish "no builds folder" (skip cross-project checks entirely) from
    # "builds folder exists but is empty" (orphan check still meaningful).
    if builds_dir.is_dir():
        build_names: set[str] | None = {p.name for p in builds_dir.iterdir() if p.is_dir()}
    else:
        build_names = None

    today = _dt.date.today()
    for pattern in sorted(patterns_dir.glob("*.md")):
        if pattern.name == "README.md":
            continue
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

        # Unused check: pattern slug appears in NO other build folder. Only
        # meaningful when there is at least one project other than the source
        # to check against — single-project workspaces can't yet compound.
        if build_names and len(build_names - {source} if source else build_names) > 0:
            slug = _pattern_slug(pattern.name)
            if slug and not _slug_used_outside_source(slug, source, builds_dir, build_names):
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


def _slug_used_outside_source(
    slug: str,
    source: str | None,
    builds_dir: Path,
    build_names: set[str],
) -> bool:
    """True if *slug* appears in any builds/<other>/ folder, not just the source one."""
    needle = slug.lower()
    for name in build_names:
        if source and name == source:
            continue
        project = builds_dir / name
        for f in project.rglob("*.md"):
            try:
                text = f.read_text(errors="replace").lower()
            except OSError:
                continue
            if needle in text:
                return True
    return False
