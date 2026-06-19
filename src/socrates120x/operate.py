"""The operator's daily rituals: decide, journal, timeline, ship, status.

Everything here reads or appends to an existing project; nothing scaffolds
or interviews.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from socrates120x.audit import _LAST_UPDATED_RE, Severity, run_audit
from socrates120x.support import _color, _dim, editor_command, locked_read_modify_write

# ─────────────────────────────────────────────────────────────────────────────
# decide — append a properly dated decision to DECISIONS.md
# Lands in a 'Decisions added after init' section so Sprint 001 history
# stays distinct; the (YYYY-MM-DD) stamp is what `socrates timeline` reads.
# ─────────────────────────────────────────────────────────────────────────────

POST_INIT_HEADING = "## Decisions added after init"
OUT_OF_SCOPE_HEADING = "## Explicitly out of scope"


def record_decision(project: Path, text: str) -> int:
    """Append a dated decision to ``project/planning/DECISIONS.md``.

    Read-modify-write is guarded by an exclusive POSIX file lock and
    the final write is atomic (tempfile + os.replace). Without those:

    - Two concurrent ``socrates decide`` invocations both read the same
      pre-write contents, both compute new bodies, both write. The
      second writer silently clobbers the first — one decision is lost.
      An operator scripting batch decisions or running them from a CI
      hook would have no way to detect the loss after the fact.
    - A SIGINT (Ctrl-C) mid-write to a 5-10 KB DECISIONS.md leaves the
      file truncated and unparseable. ``socrates timeline`` then crashes
      and ``socrates audit`` reports the project as broken.

    DECISIONS.md is the most load-bearing file in a 120x project; both
    failure modes are unacceptable. Going through
    :func:`locked_read_modify_write` addresses both at once.

    Returns a process exit code (0 success, 2 error).
    """
    decisions_path = project / "planning" / "DECISIONS.md"
    if not decisions_path.is_file():
        print(
            f"error: {decisions_path} not found — is {project} a 120x project?",
            file=sys.stderr,
        )
        return 2

    # Collapse internal whitespace runs (including newlines, tabs) to single
    # spaces. A multi-line decision (`socrates decide $'foo\nbar'`) would
    # otherwise produce a bullet whose closing `**` lands on a different
    # line, breaking markdown bold rendering and terminating the list item.
    cleaned = " ".join(text.split())
    if not cleaned:
        print("error: decision text is empty", file=sys.stderr)
        return 2

    today = _dt.date.today().isoformat()
    bullet = f"- **{cleaned} ({today})**"

    locked_read_modify_write(
        decisions_path,
        lambda current: _insert_decision(current, bullet),
    )
    print(f"Appended to {decisions_path}:")
    print(f"  {bullet}")
    return 0


def _insert_decision(body: str, bullet: str) -> str:
    """Insert *bullet* into the right section, creating the section if needed."""
    lines = body.splitlines()
    post_init_idx = _find_heading(lines, POST_INIT_HEADING)
    out_of_scope_idx = _find_heading(lines, OUT_OF_SCOPE_HEADING)

    if post_init_idx is not None:
        # Append to the existing section, just before its next heading (or end).
        insert_at = _next_heading_after(lines, post_init_idx)
        if insert_at is None:
            insert_at = len(lines)
        # Trim trailing blank lines inside the section to keep formatting tight.
        while insert_at > post_init_idx + 1 and lines[insert_at - 1] == "":
            insert_at -= 1
        lines.insert(insert_at, bullet)
        return "\n".join(lines) + ("\n" if body.endswith("\n") else "")

    # Need to create the section. Put it just before "Explicitly out of scope".
    section = ["", POST_INIT_HEADING, "", bullet, ""]
    if out_of_scope_idx is not None:
        for s in reversed(section):
            lines.insert(out_of_scope_idx, s)
        return "\n".join(lines) + ("\n" if body.endswith("\n") else "")

    # No out-of-scope heading either — append at end.
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(section[1:])
    return "\n".join(lines) + "\n"


def _find_heading(lines: list[str], heading: str) -> int | None:
    for i, line in enumerate(lines):
        if line.strip() == heading:
            return i
    return None


def _next_heading_after(lines: list[str], start: int) -> int | None:
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            return i
    return None


# ─────────────────────────────────────────────────────────────────────────────
# journal — append-only daily log
# STATE.md is the rolling snapshot; journal entries are immutable history.
# ─────────────────────────────────────────────────────────────────────────────

# Canonical entry filename: YYYY-MM-DD.md. `_list` and `_show_latest`
# must not pick up unrelated .md files (notes.md, ideas.md, README.md)
# that an operator may have dropped into the journal dir.
_ENTRY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_journal_entry(p: Path) -> bool:
    """True if *p* is a canonical journal entry file (YYYY-MM-DD.md)."""
    return p.suffix == ".md" and bool(_ENTRY_NAME.match(p.stem))


def create_or_open_entry(project: Path, *, show: bool = False, list_all: bool = False) -> int:
    """Create today's journal entry and open $EDITOR, or list/show.

    Returns a process exit code.
    """
    journal_dir = project / "planning" / "journal"
    if not journal_dir.is_dir():
        print(
            f"error: {journal_dir} does not exist — is {project} a 120x project?",
            file=sys.stderr,
        )
        return 2

    if list_all:
        return _list(journal_dir)
    if show:
        return _show_latest(journal_dir)

    today = _dt.date.today().isoformat()
    entry = journal_dir / f"{today}.md"
    is_new = not entry.exists()
    if is_new:
        entry.write_text(_template(today), encoding="utf-8")
        print(f"Created {entry}")

    cmd = editor_command()
    if cmd is None:
        if is_new:
            print("(no $EDITOR / $VISUAL set and no fallback — entry created but not opened)")
            return 0
        print(f"(no $EDITOR set — entry already exists at {entry})")
        return 0
    try:
        subprocess.run([*cmd, str(entry)], check=True)
    except subprocess.CalledProcessError as e:
        print(f"editor exited non-zero ({e.returncode}); entry preserved at {entry}",
              file=sys.stderr)
        return e.returncode
    return 0


def _template(date: str) -> str:
    return f"""# Journal — {date}

## What happened

-

## What surprised me

-

## What did not work

-

## Notes for tomorrow

-
"""


def _list(journal_dir: Path) -> int:
    entries = sorted(p for p in journal_dir.glob("*.md") if _is_journal_entry(p))
    if not entries:
        print("(no journal entries yet — run `socrates journal` to create today's)")
        return 0
    for entry in entries:
        print(entry.name.removesuffix(".md"))
    return 0


def _show_latest(journal_dir: Path) -> int:
    entries = sorted(
        (p for p in journal_dir.glob("*.md") if _is_journal_entry(p)),
        reverse=True,
    )
    if not entries:
        print("(no journal entries yet)")
        return 0
    print(entries[0].read_text(encoding="utf-8"))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# timeline — chronological feed of journal entries, sprints, decisions
# Answers 'what happened on this project, in order?' without git log.
# ─────────────────────────────────────────────────────────────────────────────

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
        date = _sprint_date(sprint)
        if date is None:
            continue
        title = f"sprint {sprint.name}"
        # Pull the requirements goal as detail if present.
        req = sprint / "requirements.md"
        detail = ""
        if req.is_file():
            detail = _extract_goal(req.read_text(errors="replace", encoding="utf-8"))
        events.append(TimelineEvent(
            date=date,
            kind=EventKind.SPRINT,
            title=title,
            detail=detail,
        ))
    return events


# A sprint folder carries no inherent date, but operators often add a
# "Last updated:" / "Created:" stamp to its files. Prefer that (it survives
# clone/rsync/restore) over the directory mtime, which any copy resets.
_SPRINT_DATE_RE = re.compile(
    r"(?:Last updated|Created)\s*:?\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE
)


def _sprint_date(sprint: Path) -> _dt.date | None:
    """Best-effort timeline date for a sprint: a labeled date stamp inside its
    files if present, else the directory mtime as a last resort."""
    for md in sorted(sprint.glob("*.md")):
        try:
            text = md.read_text(errors="replace", encoding="utf-8")
        except OSError:
            continue
        m = _SPRINT_DATE_RE.search(text)
        if m:
            try:
                return _dt.date.fromisoformat(m.group(1))
            except ValueError:
                continue
    try:
        return _dt.date.fromtimestamp(sprint.stat().st_mtime)
    except OSError:
        return None


# The date stamp `socrates decide` and `_decisions_md` both emit is
# anchored at the END of the bullet, immediately before the closing
# `**` and optional trailing whitespace. Anchoring here prevents a
# user-typed date in the decision body (e.g. "Migrate by (2024-12-31)
# (2026-05-20)") from being misread as the recording date — the
# previous unanchored `\((\d{4}-\d{2}-\d{2})\)` regex took the FIRST
# match in the line.
_DATED_DECISION_END = re.compile(r"\((\d{4}-\d{2}-\d{2})\)\*{0,2}\s*$")
# Fallback: any (YYYY-MM-DD) anywhere in the line, in case the line
# does NOT end in the canonical `)**` (older files, hand-edited
# bullets). Used only if the anchored match fails.
_DATED_DECISION_ANY = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")


def _decision_events(project: Path) -> list[TimelineEvent]:
    decisions_file = project / "planning" / "DECISIONS.md"
    if not decisions_file.is_file():
        return []
    events: list[TimelineEvent] = []
    for line in decisions_file.read_text(errors="replace", encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        m = _DATED_DECISION_END.search(stripped) or _DATED_DECISION_ANY.search(stripped)
        if not m:
            continue
        try:
            d = _dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        content = stripped[2:]  # strip "- "
        # Strip ONLY the trailing date stamp (anchored) so dates that appear
        # in the body are preserved in the rendered timeline entry.
        content = _DATED_DECISION_END.sub("", content).strip()
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


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _pad_visible(s: str, width: int) -> str:
    """Left-justify *s* to *width*, counting only visible (non-ANSI) chars.

    f-string width specifiers (``:<8``) count the invisible color-escape bytes,
    so colored status cells under-pad and the table columns drift on a TTY.
    Measure the ANSI-stripped width instead.
    """
    visible = len(_ANSI_RE.sub("", s))
    return s + " " * max(0, width - visible)


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


def _kind_marker(kind: EventKind, use_color: bool) -> str:
    label = {EventKind.SPRINT: "[sprint]", EventKind.JOURNAL: "[journal]", EventKind.DECISION: "[decision]"}[kind]
    color = {EventKind.SPRINT: "cyan", EventKind.JOURNAL: "magenta", EventKind.DECISION: "yellow"}[kind]
    return _color(label, color, use_color)


# ─────────────────────────────────────────────────────────────────────────────
# ship — sprint-close pre-flight checklist
# Composition command: audit + journal-today + extract-exists + STATE
# freshness. The four things an operator forgets at sprint close.
# ─────────────────────────────────────────────────────────────────────────────

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
    # Use the same authoritative check as `status` (_has_extract): a loose
    # ``f"`{name}`" in text`` substring would PASS ship on a candidate that
    # merely mentions the project in prose, green-lighting a sprint close on
    # work that was never extracted.
    found = _has_completed_extract(project)
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
    m = _LAST_UPDATED_RE.search(state.read_text(errors="replace", encoding="utf-8"))
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


def _marker(result: CheckResult, use_color: bool) -> str:
    glyph = {CheckResult.PASS: "✓", CheckResult.WARN: "!", CheckResult.FAIL: "✗"}[result]
    color = {CheckResult.PASS: "green", CheckResult.WARN: "yellow", CheckResult.FAIL: "red"}[result]
    return _color(glyph, color, use_color)


# ─────────────────────────────────────────────────────────────────────────────
# status — CompanyOS-level health dashboard
# One line per builds/<project>/: sprint, audit counts, STATE/journal age,
# extract done. The first thing the operator reads each morning.
# ─────────────────────────────────────────────────────────────────────────────

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
            f"{_pad_visible(audit_chunk, 8)}  {_pad_visible(state_chunk, 10)}  "
            f"{_pad_visible(journal_chunk, 10)}  {extract_chunk}"
        )
        if r.tagline:
            lines.append(f"{'':<{name_w}}    {_dim(r.tagline, use_color)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _summarize(project: Path) -> ProjectStatus:
    name = project.name
    tagline = _project_tagline(project)
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


def _project_tagline(project: Path) -> str:
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
        # Anchor to the project's own bold-name line ("**<name>** — tagline",
        # emitted by kit._agents_md) so an unrelated "**bold** — text" bullet
        # elsewhere in the file can't hijack the tagline. If the line isn't
        # found, return "" rather than a wrong guess.
        m = re.search(
            rf"\*\*{re.escape(project.name)}\*\*\s+—\s+(.+)",
            agents.read_text(errors="replace", encoding="utf-8"),
        )
        if m:
            return m.group(1).strip()
    return ""


def _extract_active_sprint(project: Path) -> str:
    sprints = project / "planning" / "sprints"
    if not sprints.is_dir():
        return "—"
    # Only NNN-slug folders are sprints; a stray scratch dir (e.g.
    # "wip-experiments") sorts above "001-…" and must not be mistaken for the
    # active sprint. Zero-padded NNN means lexicographic == numeric order.
    candidates = sorted(
        p.name for p in sprints.iterdir()
        if p.is_dir() and re.match(r"^\d{3}-", p.name)
    )
    if not candidates:
        return "—"
    # Heuristic: highest-numbered sprint folder. Strip the slug — show NNN-name
    # but truncate aggressively for table layout.
    name = candidates[-1]
    if len(name) > 18:
        name = name[:17] + "…"
    return name


def _state_age_days(project: Path) -> int | None:
    state = project / "planning" / "STATE.md"
    if not state.is_file():
        return None
    m = _LAST_UPDATED_RE.search(state.read_text(errors="replace", encoding="utf-8"))
    if not m:
        return None
    try:
        d = _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return (_dt.date.today() - d).days


def _latest_journal_age_days(project: Path) -> int | None:
    journal = project / "planning" / "journal"
    if not journal.is_dir():
        return None
    # Take the max over *parsed dates*, not raw stems. A stray non-date file
    # (notes.md, README.md) sorts lexicographically above an ISO date and,
    # under the old `max(stems)`, won the max, failed to parse, and made the
    # whole journal age read as unknown despite a fresh dated entry existing.
    dates: list[_dt.date] = []
    for p in journal.glob("*.md"):
        try:
            dates.append(_dt.date.fromisoformat(p.stem))
        except ValueError:
            continue
    if not dates:
        return None
    return (_dt.date.today() - max(dates)).days


def _has_completed_extract(project: Path) -> bool:
    """True if a *finished* pattern candidate references *project*.

    Authoritative source-of-truth for "was this project extracted", shared by
    status (`_has_extract`) and ship (`_extract_check`) so the two commands
    cannot disagree.

    - A local ``patterns/`` dir with any ``CANDIDATE-*.md`` counts (that dir
      belongs to the project itself).
    - A sibling CompanyOS ``patterns/`` dir counts only on the explicit
      ``Source project | `name``` line. A loose ``f"`{name}`" in text`` match
      would false-positive on a war story in an unrelated candidate that just
      mentions ``\\`name\\`` in prose — the exact bug ship used to carry.
    """
    # 1) Local patterns/ dir with CANDIDATE-*.md.
    local = project / "patterns"
    if local.is_dir() and any(local.glob("CANDIDATE-*.md")):
        return True
    # 2) Sibling CompanyOS patterns/ dir — authoritative marker only.
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
    return False


def _has_extract(project: Path) -> bool:
    """A project is "extracted" if a finished candidate references it, OR an
    extract is in progress (the answers file exists)."""
    if _has_completed_extract(project):
        return True
    # In-progress extract answers file.
    return (project / ".socrates-extract-answers.json").is_file()


def _age_label(days: int | None) -> str:
    if days is None:
        return "—"
    if days == 0:
        return "today"
    if days == 1:
        return "1d"
    return f"{days}d"


def _age_color(days: int | None, threshold: int) -> str:
    if days is None:
        return "dim"
    if days > threshold * 2:
        return "red"
    if days > threshold:
        return "yellow"
    return "green"
