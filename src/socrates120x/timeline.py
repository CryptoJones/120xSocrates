"""The `socrates timeline` subcommand — chronological project view.

Synthesizes a single chronological feed from:

- Journal entries (`planning/journal/YYYY-MM-DD.md`)
- Sprint folders (first appearance — based on directory mtime as a fallback)
- DECISIONS.md entries (when they include an inline date)

The goal is to answer "what happened on this project, in order?" without
forcing the operator to read `git log` or grep across files.
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class EventKind(Enum):
    SPRINT = "sprint"
    JOURNAL = "journal"
    DECISION = "decision"


@dataclass(frozen=True)
class TimelineEvent:
    date: _dt.date
    kind: EventKind
    title: str
    detail: str = ""

    @property
    def sort_key(self) -> tuple[str, int, str]:
        # Sort by date ascending, then within a date by kind so that sprints
        # come before journal entries before decisions (sprint header reads
        # naturally above its day's notes).
        return (self.date.isoformat(), self._kind_order(), self.title)

    def _kind_order(self) -> int:
        return {EventKind.SPRINT: 0, EventKind.JOURNAL: 1, EventKind.DECISION: 2}[self.kind]


def build_timeline(project: Path) -> list[TimelineEvent]:
    """Collect all events from a project folder, sorted chronologically."""
    events: list[TimelineEvent] = []
    events.extend(_journal_events(project))
    events.extend(_sprint_events(project))
    events.extend(_decision_events(project))
    return sorted(events, key=lambda e: e.sort_key)


def format_timeline(events: list[TimelineEvent], *, use_color: bool | None = None) -> str:
    if use_color is None:
        use_color = sys.stdout.isatty()
    if not events:
        return "(no timeline events found — has any planning happened yet?)"

    lines: list[str] = []
    current_date: _dt.date | None = None
    for ev in events:
        if ev.date != current_date:
            current_date = ev.date
            lines.append("")
            lines.append(_color(ev.date.isoformat(), "bold", use_color))
        marker = _kind_marker(ev.kind, use_color)
        lines.append(f"  {marker} {ev.title}")
        if ev.detail:
            for line in ev.detail.splitlines():
                lines.append(f"      {_dim(line, use_color)}")
    return "\n".join(lines).lstrip()


# ---------------------------------------------------------------------------
# Event collectors
# ---------------------------------------------------------------------------


def _journal_events(project: Path) -> list[TimelineEvent]:
    journal = project / "planning" / "journal"
    if not journal.is_dir():
        return []
    events: list[TimelineEvent] = []
    for entry in journal.glob("*.md"):
        if entry.name == "README.md":
            continue
        try:
            d = _dt.date.fromisoformat(entry.stem)
        except ValueError:
            continue
        first_line = _first_real_line(entry.read_text(errors="replace", encoding="utf-8"))
        events.append(TimelineEvent(
            date=d,
            kind=EventKind.JOURNAL,
            title="journal entry",
            detail=first_line,
        ))
    return events


def _sprint_events(project: Path) -> list[TimelineEvent]:
    sprints = project / "planning" / "sprints"
    if not sprints.is_dir():
        return []
    events: list[TimelineEvent] = []
    for sprint in sorted(p for p in sprints.iterdir() if p.is_dir()):
        if not re.match(r"^\d{3}-", sprint.name):
            continue
        # Use directory mtime as a proxy for "when did this sprint exist"?
        try:
            mtime = _dt.date.fromtimestamp(sprint.stat().st_mtime)
        except OSError:
            continue
        title = f"sprint {sprint.name}"
        # Pull the requirements goal as detail if present.
        req = sprint / "requirements.md"
        detail = ""
        if req.is_file():
            detail = _extract_goal(req.read_text(errors="replace", encoding="utf-8"))
        events.append(TimelineEvent(
            date=mtime,
            kind=EventKind.SPRINT,
            title=title,
            detail=detail,
        ))
    return events


_DATED_DECISION = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")


def _decision_events(project: Path) -> list[TimelineEvent]:
    decisions_file = project / "planning" / "DECISIONS.md"
    if not decisions_file.is_file():
        return []
    events: list[TimelineEvent] = []
    for line in decisions_file.read_text(errors="replace", encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        m = _DATED_DECISION.search(stripped)
        if not m:
            continue
        try:
            d = _dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        content = stripped[2:]  # strip "- "
        content = _DATED_DECISION.sub("", content).strip()
        content = content.strip("*").strip()
        events.append(TimelineEvent(
            date=d,
            kind=EventKind.DECISION,
            title=f"decision: {content}",
        ))
    return events


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _first_real_line(text: str) -> str:
    """First non-empty, non-heading, non-template line of a markdown file."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith("-") and len(s) <= 3:
            continue  # empty bullet from template
        return s[:120]
    return ""


def _extract_goal(text: str) -> str:
    in_goal = False
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_goal:
                break
            in_goal = "goal" in stripped.lower()
            continue
        if in_goal and stripped:
            body.append(stripped)
            if len(body) >= 2:
                break
    return " ".join(body)[:160]


_COLORS = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "magenta": "\033[35m",
}
_RESET = "\033[0m"


def _kind_marker(kind: EventKind, use_color: bool) -> str:
    label = {EventKind.SPRINT: "[sprint]", EventKind.JOURNAL: "[journal]", EventKind.DECISION: "[decision]"}[kind]
    color = {EventKind.SPRINT: "cyan", EventKind.JOURNAL: "magenta", EventKind.DECISION: "yellow"}[kind]
    return _color(label, color, use_color)


def _color(text: str, color: str, use_color: bool) -> str:
    if not use_color or color not in _COLORS:
        return text
    return f"{_COLORS[color]}{text}{_RESET}"


def _dim(text: str, use_color: bool) -> str:
    return _color(text, "dim", use_color)
