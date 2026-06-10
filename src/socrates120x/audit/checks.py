"""Audit checks. Each Check returns a list of Findings against a project path.

Principle: no false positives. A check that fires on a healthy project is worse
than one that misses a real issue — the audit will be ignored. When in doubt,
emit an INFO finding (advisory), not a WARNING or ERROR.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from socrates120x.audit.model import Finding, Severity
from socrates120x.scaffold import FILES

CONFIG_FILE = ".socrates-audit.json"

# Files that should always exist in a populated project. Subset of scaffold
# FILES — we exclude README stubs inside src/, tests/, etc. which are
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


class Check(ABC):
    """One audit check. Subclasses implement `run`."""

    name: str = ""

    @abstractmethod
    def run(self, project: Path) -> list[Finding]: ...


# ---------------------------------------------------------------------------
# Concrete checks
# ---------------------------------------------------------------------------


class RequiredFilesCheck(Check):
    """Every canonical planning file must exist."""

    name = "required-files"

    def run(self, project: Path) -> list[Finding]:
        findings: list[Finding] = []
        for rel in REQUIRED_PLANNING_FILES:
            path = project / rel
            if not path.is_file():
                findings.append(Finding(
                    check=self.name,
                    severity=Severity.ERROR,
                    message=f"missing required file: {rel}",
                    path=path,
                ))
        return findings


class ScaffoldShapeCheck(Check):
    """The full scaffold tree is *expected* but pruning is legitimate.

    Severity is INFO because operators routinely drop files that aren't relevant
    (e.g. `docs/API.md` on a non-API project). Per-project skip lists live in
    `.socrates-audit.json`:

        {"scaffold_shape": {"ignore": ["docs/API.md", "docs/PERMISSIONS.md"]}}
    """

    name = "scaffold-shape"

    def run(self, project: Path) -> list[Finding]:
        ignored = _load_ignore_list(project, "scaffold_shape")
        findings: list[Finding] = []
        for rel in FILES:
            if rel in REQUIRED_PLANNING_FILES:
                continue  # already covered by RequiredFilesCheck
            if rel in ignored:
                continue
            path = project / rel
            if not path.exists():
                findings.append(Finding(
                    check=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"scaffold file '{rel}' missing — pruning is allowed, "
                        f"but add it to .socrates-audit.json under "
                        f"['scaffold_shape']['ignore'] to silence this notice"
                    ),
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


class SprintFolderCheck(Check):
    """Each sprint folder must be named NNN-something and have all 4 required files."""

    name = "sprint-folders"
    _SPRINT_NAME = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")

    def run(self, project: Path) -> list[Finding]:
        findings: list[Finding] = []
        sprints_dir = project / "planning" / "sprints"
        if not sprints_dir.is_dir():
            return findings  # Already flagged by RequiredFilesCheck if planning/ exists.

        for child in sorted(sprints_dir.iterdir()):
            if not child.is_dir():
                continue
            if not self._SPRINT_NAME.match(child.name):
                findings.append(Finding(
                    check=self.name,
                    severity=Severity.ERROR,
                    message=(
                        f"sprint folder '{child.name}' does not match "
                        f"NNN-slug convention (e.g. '002-rebate-engine')"
                    ),
                    path=child,
                ))
                continue
            for fname in REQUIRED_SPRINT_FILES:
                if not (child / fname).is_file():
                    findings.append(Finding(
                        check=self.name,
                        severity=Severity.ERROR,
                        message=f"sprint '{child.name}' is missing {fname}",
                        path=child / fname,
                    ))
        return findings


class AdapterPointsToAgentsCheck(Check):
    """CLAUDE.md and CODEX.md should reference AGENTS.md (they are routers)."""

    name = "adapter-routing"

    def run(self, project: Path) -> list[Finding]:
        findings: list[Finding] = []
        for adapter in ("CLAUDE.md", "CODEX.md"):
            path = project / adapter
            if not path.is_file():
                continue
            text = path.read_text(errors="replace", encoding="utf-8")
            if "AGENTS.md" not in text:
                findings.append(Finding(
                    check=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"{adapter} should reference AGENTS.md so the agent "
                        f"is routed to the tool-agnostic instructions"
                    ),
                    path=path,
                ))
        return findings


class WeaselWordsCheck(Check):
    """Sprint acceptance criteria should be objectively checkable, not weaselly."""

    name = "acceptance-weasels"

    def run(self, project: Path) -> list[Finding]:
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
                            check=self.name,
                            severity=Severity.WARNING,
                            message=(
                                f"weasel phrase '{weasel}' in acceptance criterion — "
                                f"tighten to something objectively checkable"
                            ),
                            path=acc,
                            line=line_no,
                        ))
                        break  # one weasel per line is enough; don't spam
        return findings


class StateFreshnessCheck(Check):
    """STATE.md should be edited regularly. Flag if 'Last updated' is > 30 days old."""

    name = "state-freshness"
    _DATE = re.compile(r"Last updated:\s*(\d{4})-(\d{2})-(\d{2})")
    _STALE_DAYS = 30

    def run(self, project: Path) -> list[Finding]:
        state = project / "planning" / "STATE.md"
        if not state.is_file():
            return []  # Already flagged by RequiredFilesCheck.
        text = state.read_text(errors="replace", encoding="utf-8")
        m = self._DATE.search(text)
        if not m:
            return [Finding(
                check=self.name,
                severity=Severity.INFO,
                message="STATE.md does not contain a 'Last updated: YYYY-MM-DD' line",
                path=state,
            )]
        try:
            last = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return []  # Malformed date; skip rather than crash.
        age = (_dt.date.today() - last).days
        if age > self._STALE_DAYS:
            return [Finding(
                check=self.name,
                severity=Severity.WARNING,
                message=(
                    f"STATE.md last updated {age} days ago "
                    f"({last.isoformat()}) — update it before continuing"
                ),
                path=state,
            )]
        return []


class AlwaysOnRisksCheck(Check):
    """RISKS.md should include the kit's mandated 'AI is not source of truth' reminder."""

    name = "always-on-risks"

    def run(self, project: Path) -> list[Finding]:
        risks = project / "planning" / "RISKS.md"
        if not risks.is_file():
            return []
        lower = risks.read_text(errors="replace", encoding="utf-8").lower()
        if not any(phrase.lower() in lower for phrase in ALWAYS_ON_RISK_PHRASES):
            return [Finding(
                check=self.name,
                severity=Severity.INFO,
                message=(
                    "RISKS.md is missing the always-on reminder that 'AI output is "
                    "not source of truth' — recommended by the 120x methodology"
                ),
                path=risks,
            )]
        return []


class TerminologyUsedCheck(Check):
    """Terms defined in DOMAIN.md should appear in at least one other planning file."""

    name = "terminology-used"
    _TERM = re.compile(r"^\s*-\s+([A-Za-z][\w \-/]{1,40}?)\s+[—-]\s+")

    def run(self, project: Path) -> list[Finding]:
        domain = project / "planning" / "DOMAIN.md"
        if not domain.is_file():
            return []
        terms = self._extract_terms(domain.read_text(errors="replace", encoding="utf-8"))
        if not terms:
            return []

        other_text = self._concatenate_other_files(project)
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
                    check=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"term '{term}' is defined in DOMAIN.md but does not appear "
                        f"in any other planning file — is it actually used?"
                    ),
                    path=domain,
                ))
        return findings

    def _extract_terms(self, body: str) -> list[str]:
        in_terminology = False
        terms: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                in_terminology = "terminology" in stripped.lower()
                continue
            if not in_terminology:
                continue
            m = self._TERM.match(line)
            if m:
                terms.append(m.group(1).strip())
        return terms

    def _concatenate_other_files(self, project: Path) -> str:
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
ALL_CHECKS: tuple[Check, ...] = (
    RequiredFilesCheck(),
    SprintFolderCheck(),
    ScaffoldShapeCheck(),
    AdapterPointsToAgentsCheck(),
    WeaselWordsCheck(),
    StateFreshnessCheck(),
    AlwaysOnRisksCheck(),
    TerminologyUsedCheck(),
)
