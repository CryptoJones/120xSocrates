"""The pattern lifecycle — the compounding asset of the 120x method.

`extract` captures a pattern at sprint close (interview-driven); `review`
keeps the patterns/ folder honest (stale candidates, orphaned sources,
never-reused slugs).
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

from socrates120x.interview import Interview
from socrates120x.support import Question, _color

# ─────────────────────────────────────────────────────────────────────────────
# extract — sprint-close interview that captures a reusable pattern
# The third 120x deliverable (shipped system, preserved blueprint, extracted
# pattern) is the one most often skipped. This makes it cheap.
# ─────────────────────────────────────────────────────────────────────────────

PATTERN_QUESTIONS: tuple[Question, ...] = (
    Question(
        key="pattern_focus",
        prompt=(
            "Look back at this sprint. What is the single most useful thing it "
            "produced that you would re-use on a future project?"
        ),
        section="Pattern",
        type="multiline",
        help=(
            "Free text. Not a feature — a *pattern*. An approach, a piece of code, "
            "a prompt, a piece of scoping language, a workflow."
        ),
        required=True,
    ),
    Question(
        key="pattern_kind",
        prompt="What kind of artifact is it? (one short label)",
        section="Pattern",
        help=(
            "Examples: architecture-pattern, data-ingestion, validation-approach, "
            "prompt-template, scoping-language, pricing-pattern, client-comms, "
            "test-harness, parser, debugging-recipe."
        ),
        required=True,
    ),
    Question(
        key="pattern_slug",
        prompt="Name it as a short kebab-case <verb>-<noun> slug.",
        section="Pattern",
        help=(
            'Examples: validate-parsed-numbers, scope-data-projects, '
            'ingest-vendor-spreadsheets, price-internal-tools.'
        ),
        required=True,
    ),
    Question(
        key="pattern_summary",
        prompt="One sentence — what does it do?",
        section="Pattern",
        required=True,
    ),
    Question(
        key="pattern_when_applies",
        prompt="When does this pattern apply? (the trigger situation)",
        section="Applicability",
        type="multiline",
        help="Be concrete. 'When the client gives you weekly vendor spreadsheets', not 'when there is data'.",
        required=True,
    ),
    Question(
        key="pattern_when_does_not",
        prompt="When does this pattern NOT apply? (where it would break)",
        section="Applicability",
        type="multiline",
        help=(
            "Patterns that don't list their failure modes get cargo-culted. "
            "What kind of project should NOT use this?"
        ),
    ),
    Question(
        key="pattern_body",
        prompt="The pattern itself — paste the code, prompt, template, or sketch.",
        section="Body",
        type="multiline",
        help=(
            "This is the load-bearing field. Be specific enough that you could "
            "drop it into the next project unchanged. --editor mode is recommended."
        ),
        required=True,
    ),
    Question(
        key="pattern_war_story",
        prompt="What about this project taught you this pattern? (the war story)",
        section="Provenance",
        type="multiline",
        help=(
            "The story of how you discovered or earned this pattern. Important "
            "because it grounds the pattern in a real situation, not a theory."
        ),
    ),
    Question(
        key="pattern_confidence",
        prompt="Confidence level — 1 (rough draft) to 5 (battle-tested across many projects).",
        section="Provenance",
        help="A fresh extraction is usually 1 or 2.",
        default="1",
    ),
)


def run_extract(
    project: Path,
    *,
    patterns_dir: Path | None = None,
    resume: bool = False,
    editor: bool = False,
) -> tuple[int, Path | None]:
    """Run the extraction interview and write a pattern candidate.

    Returns (exit_code, path_to_pattern_file).
    """
    target_dir = patterns_dir or _resolve_patterns_dir(project)
    target_dir.mkdir(parents=True, exist_ok=True)

    answers_path = project / ".socrates-extract-answers.json"
    iv = Interview(
        answers_path=answers_path,
        resume=resume,
        editor=editor,
        questions=PATTERN_QUESTIONS,
    )
    try:
        iv.run()
    except (KeyboardInterrupt, EOFError):
        # Ctrl-C or Ctrl-D / exhausted stdin on a required question. Progress
        # is saved after every answer, so resume rather than crash.
        print(
            "\n\nExtraction interrupted. Answers saved. "
            "Re-run with --resume to pick up where you left off.",
        )
        return 130, None

    slug = _sanitize_slug(iv.answers.get("pattern_slug", "untitled"))
    target = target_dir / f"CANDIDATE-{slug}.md"
    target.write_text(render_pattern(iv.answers, project=project), encoding="utf-8")
    print(f"\nPattern candidate written to: {target}")
    print()
    print("Next steps:")
    print(f"  1. Read {target}.")
    print("  2. Tighten the body. Remove anything that does not generalise.")
    print("  3. When the pattern proves itself on a SECOND project, rename")
    print(f"     CANDIDATE-{slug}.md → {slug}.md to promote it.")
    return 0, target


def render_pattern(answers: dict[str, Any], *, project: Path) -> str:
    today = _dt.date.today().isoformat()
    summary = answers.get("pattern_summary") or "_(untitled pattern)_"
    kind = answers.get("pattern_kind") or "_(unclassified)_"
    confidence = answers.get("pattern_confidence") or "1"
    when_applies = answers.get("pattern_when_applies") or "_(not specified)_"
    when_does_not = answers.get("pattern_when_does_not") or "_(not specified)_"
    body = answers.get("pattern_body") or "_(not yet captured)_"
    war_story = answers.get("pattern_war_story") or "_(not captured)_"
    focus = answers.get("pattern_focus") or ""

    return f"""# Pattern: {_sanitize_slug(answers.get("pattern_slug", "untitled"))} (CANDIDATE)

> {summary}

| | |
|---|---|
| **Kind** | {kind} |
| **Confidence** | {confidence} / 5 |
| **Extracted** | {today} |
| **Source project** | `{project.name}` |

## When this applies

{when_applies}

## When it does NOT apply

{when_does_not}

## The pattern

{body}

## Why this pattern exists (the war story)

{war_story}

## Original focus (operator's own words at extraction time)

{focus}

---

_This is a CANDIDATE pattern — it has been observed once. Promote to a real pattern (drop the `CANDIDATE-` prefix) only after it has worked on at least one additional project._
"""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_patterns_dir(project: Path) -> Path:
    """Find the patterns/ directory.

    If *project* is inside a CompanyOS layout (i.e. it sits inside a
    `builds/` directory that has a sibling `patterns/`), use that. Otherwise
    fall back to ``project/patterns/``.
    """
    parent = project.parent
    if parent.name == "builds":
        candidate = parent.parent / "patterns"
        if candidate.is_dir() or (parent.parent / "AGENTS.md").exists():
            return candidate
    return project / "patterns"


_NON_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _sanitize_slug(raw: str) -> str:
    slug = raw.strip().lower().replace(" ", "-").replace("_", "-")
    slug = _NON_SLUG_RE.sub("", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"


# ─────────────────────────────────────────────────────────────────────────────
# patterns — review the patterns/ folder for drift
# Stale candidates (>90d), orphaned sources, never-reused slugs. The
# rgrep across builds is cached in patterns/.usage-cache.json with
# per-project mtime invalidation (schema documented at _compute_usage_map).
# ─────────────────────────────────────────────────────────────────────────────

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
        body = pattern.read_text(errors="replace", encoding="utf-8")
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
        elif is_candidate and extracted is None:
            # No parseable 'Extracted' date means staleness can't be measured —
            # don't let an abandoned candidate hide behind a broken date line.
            findings.append(PatternFinding(
                kind=FindingKind.STALE,
                path=pattern,
                message=(
                    "candidate has no valid 'Extracted: YYYY-MM-DD' date — add one, "
                    "or promote/delete it"
                ),
            ))

        # Orphan source check. Guard on a *non-empty* build set (truthy),
        # not `is not None`: an existing-but-empty builds/ (a freshly
        # scaffolded CompanyOS has only builds/README.md) is "nothing to
        # check against", not "every source is orphaned". This matches the
        # unused check below, which already guards on `if build_names`.
        if source and build_names and source not in build_names:
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
    """True if *slug* appears as a complete token in any .md file under
    *project_dir*.

    Naive substring match (the previous implementation) false-positived on
    short slugs: ``auth`` matched ``author`` / ``authentic`` / ``authority``,
    ``api`` matched ``apiary`` / ``rapidly``. The "unused candidate" report
    silently hid genuine unused patterns whenever such a short slug
    happened to be substring of a real word in any project's planning
    files.

    Word-boundary regex with custom boundary chars (``\\w`` plus ``-``)
    handles kebab-case slugs correctly: ``validate-numbers`` won't match
    inside ``validate-numbers-attempt`` (longer kebab identifier), and
    ``auth`` won't match inside ``author``.
    """
    needle = slug.lower()
    # (?<![\w-]) — not preceded by a word char or dash
    # (?![\w-])  — not followed by a word char or dash
    # re.escape protects against any regex metacharacters in slug names.
    pattern = re.compile(
        rf"(?<![\w-]){re.escape(needle)}(?![\w-])",
        flags=re.IGNORECASE,
    )
    for f in project_dir.rglob("*.md"):
        try:
            text = f.read_text(errors="replace", encoding="utf-8")
        except OSError:
            continue
        if pattern.search(text):
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
        data = json.loads(cache_path.read_text(encoding="utf-8"))
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
        kind_color = {
            FindingKind.ORPHAN: "red",
            FindingKind.STALE: "yellow",
            FindingKind.UNUSED: "yellow",
        }.get(kind, "cyan")
        lines.append(_color(f"── {kind.value} ── ({len(bucket)})", kind_color, use_color))
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


_PATTERN_SOURCE_RE = re.compile(r"\*\*Source project\*\*\s*\|\s*`([^`]+)`")
_PATTERN_EXTRACTED_RE = re.compile(r"\*\*Extracted\*\*\s*\|\s*(\d{4})-(\d{2})-(\d{2})")


def _extract_source_project(body: str) -> str | None:
    m = _PATTERN_SOURCE_RE.search(body)
    # .strip() to match audit.check_orphan_pattern_source, which strips the
    # same capture group — otherwise a hand-edited "| ` proj ` |" yields
    # divergent orphan verdicts between `patterns review` and `audit`.
    return m.group(1).strip() if m else None


def _extract_extracted_date(body: str) -> _dt.date | None:
    m = _PATTERN_EXTRACTED_RE.search(body)
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _pattern_slug(filename: str) -> str:
    name = filename.removeprefix("CANDIDATE-").removesuffix(".md")
    return name.strip()
