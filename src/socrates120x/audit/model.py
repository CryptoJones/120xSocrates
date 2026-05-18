"""Data classes shared across the audit subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(Enum):
    """How loudly an audit finding should be reported."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 0, "warning": 1, "info": 2}[self.value]


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

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def extend(self, findings: list[Finding]) -> None:
        self.findings.extend(findings)

    def by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]
