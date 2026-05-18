"""Render an AuditReport as human-readable text or JSON."""

from __future__ import annotations

import json
import sys

from socrates120x.audit.model import AuditReport, Severity

_SEV_LABEL = {
    Severity.ERROR: "ERROR",
    Severity.WARNING: "WARN ",
    Severity.INFO: "INFO ",
}

# ANSI colors — only emitted when stdout is a TTY.
_SEV_COLOR = {
    Severity.ERROR: "\033[31m",   # red
    Severity.WARNING: "\033[33m", # yellow
    Severity.INFO: "\033[36m",    # cyan
}
_RESET = "\033[0m"


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
        label = _SEV_LABEL[sev]
        if use_color:
            label = f"{_SEV_COLOR[sev]}{label}{_RESET}"
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
