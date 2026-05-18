"""CompanyOS-level audit checks.

These run against a CompanyOS root (the macro layer) rather than a single
build. They catch consistency issues that *only* exist at the cross-project
scale: orphaned clients, orphaned patterns, abandoned proposals, etc.
"""

from __future__ import annotations

import re
from pathlib import Path

from socrates120x.audit.checks import Check
from socrates120x.audit.model import Finding, Severity


class CompanyOSStructureCheck(Check):
    """The CompanyOS root must have its required folders + AGENTS.md."""

    name = "companyos-structure"
    _REQUIRED = ("AGENTS.md", "builds", "clients", "patterns", "pipeline")

    def run(self, project: Path) -> list[Finding]:
        findings: list[Finding] = []
        for rel in self._REQUIRED:
            if not (project / rel).exists():
                findings.append(Finding(
                    check=self.name,
                    severity=Severity.ERROR,
                    message=(
                        f"CompanyOS root is missing '{rel}' — run "
                        f"`socrates companyos {project}` to regenerate"
                    ),
                    path=project / rel,
                ))
        return findings


class OrphanBuildsCheck(Check):
    """A build with no corresponding clients/<name>/ folder is an orphan.

    The heuristic: a build folder's name should match SOME client folder, or
    there should be a `client` reference somewhere in the project's AGENTS.md /
    .socrates-answers.json. If neither, flag.
    """

    name = "orphan-builds"

    def run(self, project: Path) -> list[Finding]:
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
                    check=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"build '{build.name}' has no recorded client — "
                        f"add 'Client: ...' to AGENTS.md or run `socrates init` again"
                    ),
                    path=build,
                ))
                continue
            if (
                referenced_client.lower() not in client_names
                and referenced_client.lower() != "internal"
            ):
                findings.append(Finding(
                    check=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"build '{build.name}' references client "
                        f"'{referenced_client}' but no clients/{referenced_client}/ "
                        f"folder exists"
                    ),
                    path=build,
                ))
        return findings


class OrphanPatternSourceCheck(Check):
    """A pattern that references a `builds/<source>` folder that no longer exists."""

    name = "orphan-pattern-source"
    _SOURCE_LINE = re.compile(r"\*\*Source project\*\*\s*\|\s*`([^`]+)`")

    def run(self, project: Path) -> list[Finding]:
        patterns = project / "patterns"
        builds = project / "builds"
        if not patterns.is_dir() or not builds.is_dir():
            return []
        build_names = {p.name for p in builds.iterdir() if p.is_dir()}
        findings: list[Finding] = []
        for pattern in sorted(patterns.glob("*.md")):
            if pattern.name == "README.md":
                continue
            body = pattern.read_text(errors="replace")
            m = self._SOURCE_LINE.search(body)
            if not m:
                continue
            source = m.group(1).strip()
            if source not in build_names:
                findings.append(Finding(
                    check=self.name,
                    severity=Severity.WARNING,
                    message=(
                        f"pattern references source project '{source}' which "
                        f"no longer exists in builds/ — the provenance is broken"
                    ),
                    path=pattern,
                ))
        return findings


class StaleProposalCheck(Check):
    """A proposal entry that mentions a slug not present in builds/ may be stale.

    Heuristic: scan pipeline/proposals.md for backtick-wrapped slugs; for each,
    check whether that slug is the name of any directory in builds/. If not,
    emit an INFO advisory — could be an active prospect, could be a
    forgotten one.
    """

    name = "stale-proposals"
    _SLUG = re.compile(r"`([a-z][a-z0-9-]*)`")

    def run(self, project: Path) -> list[Finding]:
        proposals = project / "pipeline" / "proposals.md"
        builds = project / "builds"
        if not proposals.is_file() or not builds.is_dir():
            return []
        build_names = {p.name for p in builds.iterdir() if p.is_dir()}
        body = proposals.read_text(errors="replace")
        findings: list[Finding] = []
        seen: set[str] = set()
        for m in self._SLUG.finditer(body):
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
                    check=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"proposals.md mentions `{slug}` but no builds/{slug}/ "
                        f"exists — has the engagement started or stalled?"
                    ),
                    path=proposals,
                ))
        return findings


def _build_client_reference(build: Path) -> str | None:
    answers = build / ".socrates-answers.json"
    if answers.is_file():
        import json
        try:
            data = json.loads(answers.read_text())
            if isinstance(data, dict):
                v = data.get("client")
                if isinstance(v, str) and v.strip():
                    return v.strip()
        except (OSError, ValueError):
            pass
    agents = build / "AGENTS.md"
    if agents.is_file():
        text = agents.read_text(errors="replace")
        m = re.search(r"Client:\s*\*\*([^*\n]+)\*\*", text)
        if m:
            return m.group(1).strip()
        m = re.search(r"Client:\s*([^\n]+)", text)
        if m:
            return m.group(1).strip().strip("*").strip()
    return None


COMPANYOS_CHECKS: tuple[Check, ...] = (
    CompanyOSStructureCheck(),
    OrphanBuildsCheck(),
    OrphanPatternSourceCheck(),
    StaleProposalCheck(),
)
