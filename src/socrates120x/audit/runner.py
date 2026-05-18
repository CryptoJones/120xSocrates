"""Run every registered audit check against a project folder."""

from __future__ import annotations

from pathlib import Path

from socrates120x.audit.checks import ALL_CHECKS, Check
from socrates120x.audit.model import AuditReport


def run_audit(
    project: Path,
    *,
    checks: tuple[Check, ...] = ALL_CHECKS,
) -> AuditReport:
    """Run every check against *project* and aggregate findings into a report."""
    report = AuditReport(project_path=project)
    for check in checks:
        report.checks_run.append(check.name)
        report.extend(check.run(project))
    return report
