"""The `socrates status` subcommand — CompanyOS-level health dashboard.

Scan every `builds/<project>/` under a CompanyOS root and report a one-line
health summary per project. Designed to be the first thing the operator runs
in the morning when juggling multiple engagements.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from socrates120x.audit import run_audit
from socrates120x.audit.model import Severity

STALE_STATE_DAYS = 14
STALE_JOURNAL_DAYS = 7


@dataclass
class ProjectStatus:
    name: str
    tagline: str
    active_sprint: str
    audit_errors: int
    audit_warnings: int
    state_age_days: int | None
    journal_age_days: int | None
    has_extract: bool


def companyos_status(root: Path) -> list[ProjectStatus]:
    """Return a status summary for every project under ``root/builds/``."""
    builds = root / "builds"
    if not builds.is_dir():
        return []
    results: list[ProjectStatus] = []
    for project in sorted(p for p in builds.iterdir() if p.is_dir()):
        # Skip non-project folders (e.g. README.md sentinel files).
        if not (project / "planning").is_dir():
            continue
        results.append(_summarize(project))
    return results


def format_status(rows: list[ProjectStatus], *, use_color: bool | None = None) -> str:
    if use_color is None:
        use_color = sys.stdout.isatty()
    if not rows:
        return "(no project folders found under builds/)"

    name_w = max(8, max(len(r.name) for r in rows))
    sprint_w = max(10, max(len(r.active_sprint) for r in rows))

    lines: list[str] = []
    lines.append(
        f"{'project':<{name_w}}  {'sprint':<{sprint_w}}  "
        f"{'audit':<8}  {'STATE':<10}  {'journal':<10}  extract"
    )
    lines.append("─" * (name_w + sprint_w + 8 + 10 + 10 + 10 + 12))

    for r in rows:
        audit_chunk = _color(
            f"E{r.audit_errors}W{r.audit_warnings}",
            "red" if r.audit_errors else "yellow" if r.audit_warnings else "green",
            use_color,
        )
        state_chunk = _color(
            _age_label(r.state_age_days),
            _age_color(r.state_age_days, STALE_STATE_DAYS),
            use_color,
        )
        journal_chunk = _color(
            _age_label(r.journal_age_days),
            _age_color(r.journal_age_days, STALE_JOURNAL_DAYS),
            use_color,
        )
        extract_chunk = _color(
            "✓" if r.has_extract else "—",
            "green" if r.has_extract else "yellow",
            use_color,
        )
        lines.append(
            f"{r.name:<{name_w}}  {r.active_sprint:<{sprint_w}}  "
            f"{audit_chunk:<8}  {state_chunk:<10}  {journal_chunk:<10}  {extract_chunk}"
        )
        if r.tagline:
            lines.append(f"{'':<{name_w}}    {_dim(r.tagline, use_color)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _summarize(project: Path) -> ProjectStatus:
    name = project.name
    tagline = _extract_tagline(project)
    active = _extract_active_sprint(project)

    audit_errors = 0
    audit_warnings = 0
    try:
        report = run_audit(project)
        audit_errors = len(report.by_severity(Severity.ERROR))
        audit_warnings = len(report.by_severity(Severity.WARNING))
    except OSError:
        # Audit choked on a permission or read error — treat as 0 + 0; the
        # operator can rerun `socrates audit <project>` for the real reason.
        pass

    state_age = _state_age_days(project)
    journal_age = _latest_journal_age_days(project)
    has_extract = _has_extract(project)

    return ProjectStatus(
        name=name,
        tagline=tagline,
        active_sprint=active,
        audit_errors=audit_errors,
        audit_warnings=audit_warnings,
        state_age_days=state_age,
        journal_age_days=journal_age,
        has_extract=has_extract,
    )


def _extract_tagline(project: Path) -> str:
    answers_path = project / ".socrates-answers.json"
    if answers_path.is_file():
        try:
            data = json.loads(answers_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                t = data.get("tagline")
                if isinstance(t, str):
                    return t
        except (OSError, ValueError):
            pass
    agents = project / "AGENTS.md"
    if agents.is_file():
        m = re.search(r"\*\*[^*]+\*\*\s+—\s+(.+)", agents.read_text(errors="replace", encoding="utf-8"))
        if m:
            return m.group(1).strip()
    return ""


def _extract_active_sprint(project: Path) -> str:
    sprints = project / "planning" / "sprints"
    if not sprints.is_dir():
        return "—"
    candidates = sorted(p.name for p in sprints.iterdir() if p.is_dir())
    if not candidates:
        return "—"
    # Heuristic: highest-numbered sprint folder. Strip the slug — show NNN-name
    # but truncate aggressively for table layout.
    name = candidates[-1]
    if len(name) > 18:
        name = name[:17] + "…"
    return name


_DATE = re.compile(r"Last updated:\s*(\d{4})-(\d{2})-(\d{2})")


def _state_age_days(project: Path) -> int | None:
    state = project / "planning" / "STATE.md"
    if not state.is_file():
        return None
    m = _DATE.search(state.read_text(errors="replace", encoding="utf-8"))
    if not m:
        return None
    try:
        d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return (_dt.date.today() - d).days


def _latest_journal_age_days(project: Path) -> int | None:
    journal = project / "planning" / "journal"
    if not journal.is_dir():
        return None
    entries = [p for p in journal.glob("*.md") if p.name != "README.md"]
    if not entries:
        return None
    latest_name = max(p.stem for p in entries)
    try:
        d = _dt.date.fromisoformat(latest_name)
    except ValueError:
        return None
    return (_dt.date.today() - d).days


def _has_extract(project: Path) -> bool:
    """A project has been "extracted" if any pattern candidate references it.

    Two prior bugs fixed here:
    - Each pattern file was read TWICE (once per substring check). On a
      CompanyOS with N projects and M patterns, status() became O(N*M)
      file reads. Read once, check both patterns against the same text.
    - The fallback ``f"\\`{project.name}\\`" in text`` matched any backtick
      mention of the project — a war story in pattern P that says
      ``see \\`other-project\\` for context`` would falsely mark
      other-project as having an extract. Drop the loose fallback; only
      the explicit ``Source project | \\`name\\``` line is authoritative.
    """
    # 1) Local patterns/ dir with CANDIDATE-*.md.
    local = project / "patterns"
    if local.is_dir() and any(local.glob("CANDIDATE-*.md")):
        return True
    # 2) Sibling CompanyOS patterns/ dir.
    parent = project.parent
    if parent.name == "builds":
        sibling = parent.parent / "patterns"
        if sibling.is_dir():
            source_marker = f"Source project** | `{project.name}`"
            # Tolerate both pattern emitters' formats (markdown table cell
            # may or may not have the ** around the label depending on
            # render version).
            source_marker_alt = f"Source project | `{project.name}`"
            for f in sibling.glob("CANDIDATE-*.md"):
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if source_marker in text or source_marker_alt in text:
                    return True
    # 3) Or has an in-progress extract answers file.
    return (project / ".socrates-extract-answers.json").is_file()


def _age_label(days: int | None) -> str:
    if days is None:
        return "—"
    if days == 0:
        return "today"
    if days == 1:
        return "1d"
    return f"{days}d"


_COLORS = {
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "dim": "\033[2m",
}
_RESET = "\033[0m"


def _age_color(days: int | None, threshold: int) -> str:
    if days is None:
        return "dim"
    if days > threshold * 2:
        return "red"
    if days > threshold:
        return "yellow"
    return "green"


def _color(text: str, color: str, use_color: bool) -> str:
    if not use_color or color not in _COLORS:
        return text
    return f"{_COLORS[color]}{text}{_RESET}"


def _dim(text: str, use_color: bool) -> str:
    return _color(text, "dim", use_color)
