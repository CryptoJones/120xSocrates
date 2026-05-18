"""Run every registered audit check against a project or CompanyOS folder."""

from __future__ import annotations

from pathlib import Path

from socrates120x.audit.checks import ALL_CHECKS, Check
from socrates120x.audit.companyos_checks import COMPANYOS_CHECKS
from socrates120x.audit.model import AuditReport


def run_audit(
    target: Path,
    *,
    checks: tuple[Check, ...] | None = None,
    companyos: bool = False,
) -> AuditReport:
    """Run every check against *target* and aggregate findings into a report.

    If ``companyos`` is True (or auto-detected via :func:`looks_like_companyos`),
    the macro-level check set is used. Otherwise the per-project checks run.
    """
    if checks is None:
        checks = COMPANYOS_CHECKS if companyos else ALL_CHECKS

    report = AuditReport(project_path=target)
    for check in checks:
        report.checks_run.append(check.name)
        report.extend(check.run(target))
    return report


def looks_like_companyos(path: Path) -> bool:
    """Heuristic: a CompanyOS root has builds/, patterns/, and an AGENTS.md."""
    return (
        (path / "builds").is_dir()
        and (path / "patterns").is_dir()
        and (path / "AGENTS.md").is_file()
    )
