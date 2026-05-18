"""The `socrates ship` subcommand — sprint-close pre-flight checklist.

`ship` is a composition command, not new logic. It chains:

1. `audit --strict` — planning files must be consistent.
2. Journal-entry-today check — current operator notes must exist.
3. Extract check — at least one CANDIDATE-* pattern referencing this project
   (or an in-progress `.socrates-extract-answers.json`).
4. Active-sprint freshness check — STATE.md should already point at the
   sprint we are about to close, not a stale earlier one.

The goal is a one-command ritual at sprint close so the four things an
operator forgets become the four things `ship` forces.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from socrates120x.audit import run_audit
from socrates120x.audit.model import Severity


class CheckResult(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class ShipFinding:
    name: str
    result: CheckResult
    message: str


def preflight(project: Path) -> list[ShipFinding]:
    """Run every pre-flight check. Returns findings in display order."""
    findings: list[ShipFinding] = []

    # 1. Audit must be clean (errors fail; warnings warn).
    findings.append(_audit_check(project))

    # 2. Journal entry for today exists.
    findings.append(_journal_check(project))

    # 3. Extract has been started or completed for this project.
    findings.append(_extract_check(project))

    # 4. STATE.md was touched recently (within 7 days of today).
    findings.append(_state_check(project))

    return findings


def format_preflight(findings: list[ShipFinding], *, use_color: bool | None = None) -> str:
    if use_color is None:
        use_color = sys.stdout.isatty()
    lines = ["socrates ship — sprint-close pre-flight", ""]
    for f in findings:
        marker = _marker(f.result, use_color)
        lines.append(f"  {marker} {f.name}: {f.message}")
    lines.append("")
    failures = [f for f in findings if f.result is CheckResult.FAIL]
    warnings = [f for f in findings if f.result is CheckResult.WARN]
    if failures:
        lines.append(_color(
            f"  ✗ {len(failures)} blocker(s); fix before shipping.",
            "red", use_color,
        ))
    elif warnings:
        lines.append(_color(
            f"  ! {len(warnings)} advisory; sprint is shippable but tighten before next.",
            "yellow", use_color,
        ))
    else:
        lines.append(_color("  ✓ cleared for sprint close.", "green", use_color))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _audit_check(project: Path) -> ShipFinding:
    report = run_audit(project)
    errors = len(report.by_severity(Severity.ERROR))
    warnings = len(report.by_severity(Severity.WARNING))
    if errors:
        return ShipFinding(
            name="audit",
            result=CheckResult.FAIL,
            message=f"{errors} error(s), {warnings} warning(s) — run `socrates audit` for details",
        )
    if warnings:
        return ShipFinding(
            name="audit",
            result=CheckResult.WARN,
            message=f"{warnings} warning(s) — not a blocker but worth tightening",
        )
    return ShipFinding(name="audit", result=CheckResult.PASS, message="planning is clean")


def _journal_check(project: Path) -> ShipFinding:
    today = _dt.date.today()
    entry = project / "planning" / "journal" / f"{today.isoformat()}.md"
    if entry.is_file():
        return ShipFinding(
            name="journal",
            result=CheckResult.PASS,
            message=f"today's entry ({today.isoformat()}) exists",
        )
    return ShipFinding(
        name="journal",
        result=CheckResult.WARN,
        message=(
            "no journal entry for today — run `socrates journal` to log what "
            "happened before declaring the sprint complete"
        ),
    )


def _extract_check(project: Path) -> ShipFinding:
    # Look for both local and CompanyOS-sibling patterns dirs.
    candidate_locations = [project / "patterns"]
    if project.parent.name == "builds":
        candidate_locations.append(project.parent.parent / "patterns")

    found = False
    for loc in candidate_locations:
        if not loc.is_dir():
            continue
        for f in loc.glob("CANDIDATE-*.md"):
            text = f.read_text(errors="replace")
            if f"`{project.name}`" in text:
                found = True
                break
        if found:
            break

    in_progress = (project / ".socrates-extract-answers.json").is_file()

    if found:
        return ShipFinding(
            name="extract",
            result=CheckResult.PASS,
            message="at least one pattern candidate references this project",
        )
    if in_progress:
        return ShipFinding(
            name="extract",
            result=CheckResult.WARN,
            message="extract started but no pattern committed yet — re-run `socrates extract`",
        )
    return ShipFinding(
        name="extract",
        result=CheckResult.WARN,
        message=(
            "no pattern extracted for this sprint — run `socrates extract` "
            "before close (the third 120x deliverable is the one operators "
            "skip; ship blocks the habit from forming)"
        ),
    )


def _state_check(project: Path) -> ShipFinding:
    state = project / "planning" / "STATE.md"
    if not state.is_file():
        return ShipFinding(
            name="state",
            result=CheckResult.FAIL,
            message="planning/STATE.md missing",
        )
    answers_path = project / ".socrates-answers.json"
    if answers_path.is_file():
        try:
            data = json.loads(answers_path.read_text())
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("state_next"):
            # If state_next references the NEXT sprint, we can be confident
            # STATE is current-sprint-aware.
            pass
    # Fall back to recency check via the embedded date.
    import re
    m = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", state.read_text(errors="replace"))
    if not m:
        return ShipFinding(
            name="state",
            result=CheckResult.WARN,
            message="STATE.md has no 'Last updated' line — add one",
        )
    try:
        last = _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return ShipFinding(
            name="state",
            result=CheckResult.WARN,
            message="STATE.md 'Last updated' date is unparseable",
        )
    age = (_dt.date.today() - last).days
    if age > 7:
        return ShipFinding(
            name="state",
            result=CheckResult.WARN,
            message=f"STATE.md last touched {age} days ago — refresh before close",
        )
    return ShipFinding(
        name="state",
        result=CheckResult.PASS,
        message=f"STATE.md updated {age} day(s) ago",
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


_COLORS = {
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
}
_RESET = "\033[0m"


def _marker(result: CheckResult, use_color: bool) -> str:
    glyph = {CheckResult.PASS: "✓", CheckResult.WARN: "!", CheckResult.FAIL: "✗"}[result]
    color = {CheckResult.PASS: "green", CheckResult.WARN: "yellow", CheckResult.FAIL: "red"}[result]
    return _color(glyph, color, use_color)


def _color(text: str, color: str, use_color: bool) -> str:
    if not use_color or color not in _COLORS:
        return text
    return f"{_COLORS[color]}{text}{_RESET}"
