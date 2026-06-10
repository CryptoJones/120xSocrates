"""Consistency checks for projects and CompanyOS roots.

Principle: no false positives. A check that fires on a healthy project is
worse than one that misses a real issue — the audit will be ignored. When
in doubt, emit an INFO finding (advisory), not a WARNING or ERROR.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from socrates120x.kit import PROJECT_FILES
from socrates120x.patterns import _PATTERN_SOURCE_RE
from socrates120x.support import _color

# ─────────────────────────────────────────────────────────────────────────────
# audit — consistency checks for projects and CompanyOS roots
# Principle: no false positives. A check that fires on a healthy project is
# worse than one that misses a real issue — the audit will be ignored. When
# in doubt, emit an INFO finding (advisory), not a WARNING or ERROR.
# ─────────────────────────────────────────────────────────────────────────────


class Severity(Enum):
    """How loudly an audit finding should be reported."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    """One thing the auditor noticed."""

    check: str
    severity: Severity
    message: str
    path: Path | None = None
    line: int | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "check": self.check,
            "severity": self.severity.value,
            "message": self.message,
            "path": str(self.path) if self.path else None,
            "line": self.line,
        }


@dataclass
class AuditReport:
    """The full result of an audit run."""

    project_path: Path
    findings: list[Finding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]


# An audit check is just a function: project path in, findings out.
AuditCheck = Callable[[Path], list[Finding]]

CONFIG_FILE = ".socrates-audit.json"

# Files that should always exist in a populated project. Subset of
# PROJECT_FILES — we exclude README stubs inside src/, tests/, etc. which are
# allowed to be empty and don't carry planning content.
REQUIRED_PLANNING_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "README.md",
    "planning/STATE.md",
    "planning/DECISIONS.md",
    "planning/DOMAIN.md",
    "planning/RISKS.md",
    "planning/QUESTIONS.md",
)

REQUIRED_SPRINT_FILES = (
    "requirements.md",
    "blueprint.md",
    "acceptance.md",
    "handoff-prompt.md",
)

# Words/phrases that hint at lazy acceptance criteria. Conservative list —
# common-but-vague words like "fast" or "good" are NOT here because they
# legitimately appear in client domains. Only flag clear weasels.
WEASEL_WORDS = (
    "TBD",
    "as needed",
    "as appropriate",
    "etc.",
    "and so on",
    "best practices",
    "future-proof",
    "robust enough",
    "where applicable",
)

ALWAYS_ON_RISK_PHRASES = (
    "AI output is not source of truth",
    "ai output must not become the source of truth",
    "ai is not the source of truth",
)

_LAST_UPDATED_RE = re.compile(r"Last updated:\s*(\d{4}-\d{2}-\d{2})")
_SPRINT_NAME_RE = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")
_TERM_RE = re.compile(r"^\s*-\s+([A-Za-z][\w \-/]{1,40}?)\s+[—-]\s+")
_STATE_STALE_DAYS = 30


def check_required_files(project: Path) -> list[Finding]:
    """Every canonical planning file must exist."""
    findings: list[Finding] = []
    for rel in REQUIRED_PLANNING_FILES:
        path = project / rel
        if not path.is_file():
            findings.append(Finding(
                "required-files", Severity.ERROR,
                f"missing required file: {rel}",
                path=path,
            ))
    return findings


def check_sprint_folders(project: Path) -> list[Finding]:
    """Each sprint folder must be named NNN-something and have all 4 required files."""
    findings: list[Finding] = []
    sprints_dir = project / "planning" / "sprints"
    if not sprints_dir.is_dir():
        return findings  # Already flagged by check_required_files if planning/ exists.

    for child in sorted(sprints_dir.iterdir()):
        if not child.is_dir():
            continue
        if not _SPRINT_NAME_RE.match(child.name):
            findings.append(Finding(
                "sprint-folders", Severity.ERROR,
                f"sprint folder '{child.name}' does not match "
                f"NNN-slug convention (e.g. '002-rebate-engine')",
                path=child,
            ))
            continue
        for fname in REQUIRED_SPRINT_FILES:
            if not (child / fname).is_file():
                findings.append(Finding(
                    "sprint-folders", Severity.ERROR,
                    f"sprint '{child.name}' is missing {fname}",
                    path=child / fname,
                ))
    return findings


def check_scaffold_shape(project: Path) -> list[Finding]:
    """The full scaffold tree is *expected* but pruning is legitimate.

    Severity is INFO because operators routinely drop files that aren't relevant
    (e.g. `docs/API.md` on a non-API project). Per-project skip lists live in
    `.socrates-audit.json`:

        {"scaffold_shape": {"ignore": ["docs/API.md", "docs/PERMISSIONS.md"]}}
    """
    ignored = _load_ignore_list(project, "scaffold_shape")
    findings: list[Finding] = []
    for rel in PROJECT_FILES:
        if rel in REQUIRED_PLANNING_FILES:
            continue  # already covered by check_required_files
        if rel in ignored:
            continue
        path = project / rel
        if not path.exists():
            findings.append(Finding(
                "scaffold-shape", Severity.INFO,
                f"scaffold file '{rel}' missing — pruning is allowed, "
                f"but add it to .socrates-audit.json under "
                f"['scaffold_shape']['ignore'] to silence this notice",
                path=path,
            ))
    return findings


def _load_ignore_list(project: Path, section: str) -> set[str]:
    """Load `[section]['ignore']` from `.socrates-audit.json` if present."""
    config_path = project / CONFIG_FILE
    if not config_path.is_file():
        return set()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    sec = data.get(section)
    if not isinstance(sec, dict):
        return set()
    ignore = sec.get("ignore")
    if not isinstance(ignore, list):
        return set()
    return {str(x) for x in ignore}


def check_adapter_routing(project: Path) -> list[Finding]:
    """CLAUDE.md and CODEX.md should reference AGENTS.md (they are routers)."""
    findings: list[Finding] = []
    for adapter in ("CLAUDE.md", "CODEX.md"):
        path = project / adapter
        if not path.is_file():
            continue
        text = path.read_text(errors="replace", encoding="utf-8")
        if "AGENTS.md" not in text:
            findings.append(Finding(
                "adapter-routing", Severity.WARNING,
                f"{adapter} should reference AGENTS.md so the agent "
                f"is routed to the tool-agnostic instructions",
                path=path,
            ))
    return findings


def check_acceptance_weasels(project: Path) -> list[Finding]:
    """Sprint acceptance criteria should be objectively checkable, not weaselly."""
    findings: list[Finding] = []
    sprints_dir = project / "planning" / "sprints"
    if not sprints_dir.is_dir():
        return findings

    for sprint in sorted(sprints_dir.iterdir()):
        if not sprint.is_dir():
            continue
        acc = sprint / "acceptance.md"
        if not acc.is_file():
            continue
        for line_no, line in enumerate(acc.read_text(errors="replace", encoding="utf-8").splitlines(), 1):
            lower = line.lower()
            for weasel in WEASEL_WORDS:
                if weasel.lower() in lower:
                    findings.append(Finding(
                        "acceptance-weasels", Severity.WARNING,
                        f"weasel phrase '{weasel}' in acceptance criterion — "
                        f"tighten to something objectively checkable",
                        path=acc,
                        line=line_no,
                    ))
                    break  # one weasel per line is enough; don't spam
    return findings


def check_state_freshness(project: Path) -> list[Finding]:
    """STATE.md should be edited regularly. Flag if 'Last updated' is > 30 days old."""
    state = project / "planning" / "STATE.md"
    if not state.is_file():
        return []  # Already flagged by check_required_files.
    m = _LAST_UPDATED_RE.search(state.read_text(errors="replace", encoding="utf-8"))
    if not m:
        return [Finding(
            "state-freshness", Severity.INFO,
            "STATE.md does not contain a 'Last updated: YYYY-MM-DD' line",
            path=state,
        )]
    try:
        last = _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return []  # Malformed date; skip rather than crash.
    age = (_dt.date.today() - last).days
    if age > _STATE_STALE_DAYS:
        return [Finding(
            "state-freshness", Severity.WARNING,
            f"STATE.md last updated {age} days ago "
            f"({last.isoformat()}) — update it before continuing",
            path=state,
        )]
    return []


def check_always_on_risks(project: Path) -> list[Finding]:
    """RISKS.md should include the kit's mandated 'AI is not source of truth' reminder."""
    risks = project / "planning" / "RISKS.md"
    if not risks.is_file():
        return []
    lower = risks.read_text(errors="replace", encoding="utf-8").lower()
    if not any(phrase.lower() in lower for phrase in ALWAYS_ON_RISK_PHRASES):
        return [Finding(
            "always-on-risks", Severity.INFO,
            "RISKS.md is missing the always-on reminder that 'AI output is "
            "not source of truth' — recommended by the 120x methodology",
            path=risks,
        )]
    return []


def check_terminology_used(project: Path) -> list[Finding]:
    """Terms defined in DOMAIN.md should appear in at least one other planning file."""
    domain = project / "planning" / "DOMAIN.md"
    if not domain.is_file():
        return []
    terms = _domain_terms(domain.read_text(errors="replace", encoding="utf-8"))
    if not terms:
        return []

    other_text = _other_planning_text(project)
    findings: list[Finding] = []
    for term in terms:
        # Conservative: skip very short terms (single token, <= 3 chars).
        # They risk false-positive matches against unrelated text.
        if len(term) <= 3:
            continue
        # Word-boundary regex with kebab-friendly boundary chars (\w + -).
        # Naive substring search false-positived: a defined term like
        # "tier" matched "tiers", "outlier", "vintner" in any other file
        # and silently suppressed the "term defined but unused" warning.
        pattern = re.compile(
            rf"(?<![\w-]){re.escape(term)}(?![\w-])",
            flags=re.IGNORECASE,
        )
        if not pattern.search(other_text):
            findings.append(Finding(
                "terminology-used", Severity.INFO,
                f"term '{term}' is defined in DOMAIN.md but does not appear "
                f"in any other planning file — is it actually used?",
                path=domain,
            ))
    return findings


def _domain_terms(body: str) -> list[str]:
    in_terminology = False
    terms: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_terminology = "terminology" in stripped.lower()
            continue
        if not in_terminology:
            continue
        m = _TERM_RE.match(line)
        if m:
            terms.append(m.group(1).strip())
    return terms


def _other_planning_text(project: Path) -> str:
    parts: list[str] = []
    candidates = [
        "AGENTS.md", "README.md",
        "planning/STATE.md", "planning/DECISIONS.md",
        "planning/RISKS.md", "planning/QUESTIONS.md",
    ]
    for rel in candidates:
        path = project / rel
        if path.is_file():
            parts.append(path.read_text(errors="replace", encoding="utf-8"))
    # Also include sprint files.
    sprints = project / "planning" / "sprints"
    if sprints.is_dir():
        for sprint in sprints.iterdir():
            if not sprint.is_dir():
                continue
            for f in sprint.glob("*.md"):
                parts.append(f.read_text(errors="replace", encoding="utf-8"))
    return "\n".join(parts)


# Order matters: structural checks first (ERROR-class), then content checks.
PROJECT_CHECKS: tuple[tuple[str, AuditCheck], ...] = (
    ("required-files", check_required_files),
    ("sprint-folders", check_sprint_folders),
    ("scaffold-shape", check_scaffold_shape),
    ("adapter-routing", check_adapter_routing),
    ("acceptance-weasels", check_acceptance_weasels),
    ("state-freshness", check_state_freshness),
    ("always-on-risks", check_always_on_risks),
    ("terminology-used", check_terminology_used),
)


# ── CompanyOS-level checks ───────────────────────────────────────────────────
# These run against a CompanyOS root (the macro layer) rather than a single
# build. They catch consistency issues that *only* exist at the cross-project
# scale: orphaned clients, orphaned patterns, abandoned proposals, etc.

_PROPOSAL_SLUG_RE = re.compile(r"`([a-z][a-z0-9-]*)`")


def check_companyos_structure(project: Path) -> list[Finding]:
    """The CompanyOS root must have its required folders + AGENTS.md."""
    findings: list[Finding] = []
    for rel in ("AGENTS.md", "builds", "clients", "patterns", "pipeline"):
        if not (project / rel).exists():
            findings.append(Finding(
                "companyos-structure", Severity.ERROR,
                f"CompanyOS root is missing '{rel}' — run "
                f"`socrates companyos {project}` to regenerate",
                path=project / rel,
            ))
    return findings


def check_orphan_builds(project: Path) -> list[Finding]:
    """A build with no recorded client, or one whose client folder is missing.

    The heuristic: a build folder's name should match SOME client folder, or
    there should be a `client` reference somewhere in the project's AGENTS.md /
    .socrates-answers.json. If neither, flag.
    """
    builds = project / "builds"
    clients = project / "clients"
    if not builds.is_dir() or not clients.is_dir():
        return []
    client_names = {p.name.lower() for p in clients.iterdir() if p.is_dir()}
    findings: list[Finding] = []
    for build in sorted(builds.iterdir()):
        if not build.is_dir() or not (build / "planning").is_dir():
            continue
        referenced_client = _build_client_reference(build)
        if not referenced_client:
            findings.append(Finding(
                "orphan-builds", Severity.INFO,
                f"build '{build.name}' has no recorded client — "
                f"add 'Client: ...' to AGENTS.md or run `socrates init` again",
                path=build,
            ))
            continue
        if (
            referenced_client.lower() not in client_names
            and referenced_client.lower() != "internal"
        ):
            findings.append(Finding(
                "orphan-builds", Severity.WARNING,
                f"build '{build.name}' references client "
                f"'{referenced_client}' but no clients/{referenced_client}/ "
                f"folder exists",
                path=build,
            ))
    return findings


def check_orphan_pattern_source(project: Path) -> list[Finding]:
    """A pattern that references a `builds/<source>` folder that no longer exists."""
    patterns = project / "patterns"
    builds = project / "builds"
    if not patterns.is_dir() or not builds.is_dir():
        return []
    build_names = {p.name for p in builds.iterdir() if p.is_dir()}
    findings: list[Finding] = []
    for pattern in sorted(patterns.glob("*.md")):
        if pattern.name == "README.md":
            continue
        body = pattern.read_text(errors="replace", encoding="utf-8")
        m = _PATTERN_SOURCE_RE.search(body)
        if not m:
            continue
        source = m.group(1).strip()
        if source not in build_names:
            findings.append(Finding(
                "orphan-pattern-source", Severity.WARNING,
                f"pattern references source project '{source}' which "
                f"no longer exists in builds/ — the provenance is broken",
                path=pattern,
            ))
    return findings


def check_stale_proposals(project: Path) -> list[Finding]:
    """A proposal entry that mentions a slug not present in builds/ may be stale.

    Heuristic: scan pipeline/proposals.md for backtick-wrapped slugs; for each,
    check whether that slug is the name of any directory in builds/. If not,
    emit an INFO advisory — could be an active prospect, could be a
    forgotten one.
    """
    proposals = project / "pipeline" / "proposals.md"
    builds = project / "builds"
    if not proposals.is_file() or not builds.is_dir():
        return []
    build_names = {p.name for p in builds.iterdir() if p.is_dir()}
    body = proposals.read_text(errors="replace", encoding="utf-8")
    findings: list[Finding] = []
    seen: set[str] = set()
    for m in _PROPOSAL_SLUG_RE.finditer(body):
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        # Common false-positive: `python`, `markdown`, etc. — only flag
        # slugs that contain a hyphen (real project names usually do).
        if "-" not in slug:
            continue
        if slug not in build_names:
            findings.append(Finding(
                "stale-proposals", Severity.INFO,
                f"proposals.md mentions `{slug}` but no builds/{slug}/ "
                f"exists — has the engagement started or stalled?",
                path=proposals,
            ))
    return findings


def _build_client_reference(build: Path) -> str | None:
    answers = build / ".socrates-answers.json"
    if answers.is_file():
        try:
            data = json.loads(answers.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                v = data.get("client")
                if isinstance(v, str) and v.strip():
                    return v.strip()
        except (OSError, ValueError):
            pass
    agents = build / "AGENTS.md"
    if agents.is_file():
        text = agents.read_text(errors="replace", encoding="utf-8")
        m = re.search(r"Client:\s*\*\*([^*\n]+)\*\*", text)
        if m:
            return m.group(1).strip()
        m = re.search(r"Client:\s*([^\n]+)", text)
        if m:
            return m.group(1).strip().strip("*").strip()
    return None


COMPANYOS_CHECKS: tuple[tuple[str, AuditCheck], ...] = (
    ("companyos-structure", check_companyos_structure),
    ("orphan-builds", check_orphan_builds),
    ("orphan-pattern-source", check_orphan_pattern_source),
    ("stale-proposals", check_stale_proposals),
)


# ── runner + report formatting ───────────────────────────────────────────────


def run_audit(
    target: Path,
    *,
    checks: tuple[tuple[str, AuditCheck], ...] | None = None,
    companyos: bool = False,
) -> AuditReport:
    """Run every check against *target* and aggregate findings into a report.

    If ``companyos`` is True (or auto-detected via :func:`looks_like_companyos`),
    the macro-level check set is used. Otherwise the per-project checks run.
    """
    if checks is None:
        checks = COMPANYOS_CHECKS if companyos else PROJECT_CHECKS

    report = AuditReport(project_path=target)
    for name, check in checks:
        report.checks_run.append(name)
        report.findings.extend(check(target))
    return report


def looks_like_companyos(path: Path) -> bool:
    """Heuristic: a CompanyOS root has builds/, patterns/, and an AGENTS.md."""
    return (
        (path / "builds").is_dir()
        and (path / "patterns").is_dir()
        and (path / "AGENTS.md").is_file()
    )


_SEV_LABEL = {Severity.ERROR: "ERROR", Severity.WARNING: "WARN ", Severity.INFO: "INFO "}
_SEV_COLOR = {Severity.ERROR: "red", Severity.WARNING: "yellow", Severity.INFO: "cyan"}


def format_report(report: AuditReport, *, as_json: bool = False) -> str:
    if as_json:
        return _format_json(report)
    return _format_text(report)


def _format_json(report: AuditReport) -> str:
    return json.dumps(
        {
            "project_path": str(report.project_path),
            "checks_run": report.checks_run,
            "findings": [f.to_dict() for f in report.findings],
            "counts": {
                "errors": len(report.by_severity(Severity.ERROR)),
                "warnings": len(report.by_severity(Severity.WARNING)),
                "info": len(report.by_severity(Severity.INFO)),
            },
        },
        indent=2,
    )


def _format_text(report: AuditReport) -> str:
    use_color = sys.stdout.isatty()
    lines: list[str] = []
    lines.append(f"socrates audit — {report.project_path}")
    lines.append(f"  ran {len(report.checks_run)} checks: {', '.join(report.checks_run)}")
    lines.append("")

    if not report.findings:
        lines.append("✓ no findings — planning files look internally consistent")
        return "\n".join(lines)

    # Group by severity, ERROR first.
    for sev in (Severity.ERROR, Severity.WARNING, Severity.INFO):
        bucket = report.by_severity(sev)
        if not bucket:
            continue
        label = _color(_SEV_LABEL[sev], _SEV_COLOR[sev], use_color)
        lines.append(f"── {label} ── ({len(bucket)})")
        for f in bucket:
            location = ""
            if f.path:
                try:
                    rel = f.path.relative_to(report.project_path)
                except ValueError:
                    rel = f.path
                location = f"  {rel}"
                if f.line is not None:
                    location += f":{f.line}"
            lines.append(f"  [{f.check}] {f.message}{location}")
        lines.append("")

    counts = (
        f"{len(report.by_severity(Severity.ERROR))} errors, "
        f"{len(report.by_severity(Severity.WARNING))} warnings, "
        f"{len(report.by_severity(Severity.INFO))} info"
    )
    lines.append(counts)
    return "\n".join(lines)
