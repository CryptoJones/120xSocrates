"""Regression tests for the review-finding fixes integrated onto main.

Each test pins a specific confirmed bug so it cannot silently come back.
Grouped by the module the fix lives in.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# prompting / interview — EOF on a dead stream must abort, not spin/recurse
# ---------------------------------------------------------------------------


def _dead_input(_prompt: str) -> str:
    raise EOFError


def test_ask_line_required_no_default_raises_on_eof() -> None:
    from socrates120x.prompting import Question, _ask_line

    q = Question(key="client", prompt="?", section="x", required=True)
    # Old behavior: `continue` looped forever (CPU spin). Now: re-raise.
    with pytest.raises(EOFError):
        _ask_line(_dead_input, lambda _s: None, q)


def test_ask_line_uses_default_on_eof() -> None:
    from socrates120x.prompting import Question, _ask_line

    q = Question(key="tech", prompt="?", section="x", default="TBD")
    assert _ask_line(_dead_input, lambda _s: None, q) == "TBD"


def test_ask_line_optional_returns_empty_on_eof() -> None:
    from socrates120x.prompting import Question, _ask_line

    q = Question(key="x", prompt="?", section="x")  # not required, no default
    assert _ask_line(_dead_input, lambda _s: None, q) == ""


def test_ask_multiline_required_raises_on_eof_not_recursionerror() -> None:
    from socrates120x.prompting import Question, _ask_multiline

    q = Question(key="goal", prompt="?", section="x", type="multiline", required=True)
    with pytest.raises(EOFError):
        _ask_multiline(_dead_input, lambda _s: None, q)


def test_interview_run_aborts_cleanly_on_exhausted_stdin() -> None:
    from socrates120x.interview import Interview

    iv = Interview(answers_path=Path("/tmp/unused-eof-answers.json"), project_name="p")
    # The first init question (`client`) is required with no default; a dead
    # stream must surface EOFError (which cli catches) rather than hang.
    with pytest.raises(EOFError):
        iv.run(input_fn=_dead_input, output_fn=lambda _s: None)


def test_editor_command_shlex_splits_quoted_args(monkeypatch: pytest.MonkeyPatch) -> None:
    from socrates120x.prompting import editor_command

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "emacsclient -a 'emacs'")
    assert editor_command() == ["emacsclient", "-a", "emacs"]

    # A quoted path-with-spaces survives as one arg (naive str.split broke it).
    monkeypatch.setenv("EDITOR", '"/path with space/code" --wait')
    assert editor_command() == ["/path with space/code", "--wait"]


def test_interview_corrupt_resume_warns_and_starts_fresh(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from socrates120x.interview import Interview

    answers = tmp_path / ".socrates-answers.json"
    answers.write_text('{"k": "v"', encoding="utf-8")  # truncated JSON
    iv = Interview(answers_path=answers, project_name="p", resume=True)
    iv.load()  # must not raise
    assert iv.answers == {}
    assert "warning" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# audit — word-boundary matching kills the --strict false positives
# ---------------------------------------------------------------------------


def _project_with_acceptance(tmp_path: Path, acceptance_body: str) -> Path:
    sprint = tmp_path / "planning" / "sprints" / "001-x"
    sprint.mkdir(parents=True)
    (sprint / "acceptance.md").write_text(acceptance_body, encoding="utf-8")
    return tmp_path


def test_weasel_check_no_false_positive_on_substrings(tmp_path: Path) -> None:
    from socrates120x.audit.checks import WeaselWordsCheck

    proj = _project_with_acceptance(
        tmp_path,
        "# acceptance\n- STBD pin connector is seated\n- has needed review\n",
    )
    assert WeaselWordsCheck().run(proj) == []


def test_weasel_check_still_flags_real_weasels(tmp_path: Path) -> None:
    from socrates120x.audit.checks import WeaselWordsCheck

    proj = _project_with_acceptance(
        tmp_path, "# acceptance\n- behavior is TBD\n- handle edge cases etc.\n"
    )
    msgs = [f.message for f in WeaselWordsCheck().run(proj)]
    assert any("TBD" in m for m in msgs)
    assert any("etc." in m for m in msgs)


def test_terminology_check_word_boundary(tmp_path: Path) -> None:
    from socrates120x.audit.checks import TerminologyUsedCheck

    (tmp_path / "planning").mkdir(parents=True)
    (tmp_path / "planning" / "DOMAIN.md").write_text(
        "## Terminology\n- auth — the login flow\n", encoding="utf-8"
    )
    # "auth" appears only inside "author" — must still be reported as unused.
    (tmp_path / "AGENTS.md").write_text(
        "The author wrote this.", encoding="utf-8"
    )
    msgs = [f.message for f in TerminologyUsedCheck().run(tmp_path)]
    assert any("auth" in m for m in msgs), "boundary should treat 'author' as not-a-use"

    # When the whole token appears, no finding.
    (tmp_path / "AGENTS.md").write_text("We use auth here.", encoding="utf-8")
    assert TerminologyUsedCheck().run(tmp_path) == []


# ---------------------------------------------------------------------------
# companyos audit — orphan-pattern-source is case-insensitive
# ---------------------------------------------------------------------------


def test_orphan_pattern_source_case_insensitive(tmp_path: Path) -> None:
    from socrates120x.audit.companyos_checks import OrphanPatternSourceCheck

    (tmp_path / "builds" / "alpha").mkdir(parents=True)
    patterns = tmp_path / "patterns"
    patterns.mkdir()
    (patterns / "CANDIDATE-x.md").write_text(
        "| **Source project** | `Alpha` |\n", encoding="utf-8"
    )
    # source 'Alpha' vs dir 'alpha' must NOT be flagged orphaned.
    assert OrphanPatternSourceCheck().run(tmp_path) == []

    (patterns / "CANDIDATE-y.md").write_text(
        "| **Source project** | `ghost` |\n", encoding="utf-8"
    )
    msgs = [f.message for f in OrphanPatternSourceCheck().run(tmp_path)]
    assert any("ghost" in m for m in msgs)


# ---------------------------------------------------------------------------
# sprint resolution — canonical NNN- filter + numeric order, agreed across cmds
# ---------------------------------------------------------------------------


def _project_with_sprints(tmp_path: Path, names: list[str]) -> Path:
    sprints = tmp_path / "planning" / "sprints"
    for n in names:
        d = sprints / n
        d.mkdir(parents=True)
        for f in ("requirements.md", "blueprint.md", "acceptance.md", "handoff-prompt.md"):
            (d / f).write_text("# stub", encoding="utf-8")
    return tmp_path


def test_active_sprint_ignores_noncanonical_and_picks_highest(tmp_path: Path) -> None:
    from socrates120x.onboard import _active_sprint_path
    from socrates120x.pack import _resolve_sprint
    from socrates120x.status import _extract_active_sprint

    proj = _project_with_sprints(
        tmp_path, ["001-discovery", "002-build", "9-hotfix", "draft-notes"]
    )
    # Old code sorted ALL dirs lexically and picked "draft-notes"/"9-hotfix".
    onboard_path = _active_sprint_path(proj)
    assert onboard_path is not None and onboard_path.name == "002-build"
    pack_path = _resolve_sprint(proj, None)
    assert pack_path is not None and pack_path.name == "002-build"
    assert _extract_active_sprint(proj) == "002-build"


def test_active_sprint_numeric_beyond_lexical(tmp_path: Path) -> None:
    from socrates120x.onboard import _active_sprint_path

    # All canonical; 010 must beat 002 (numeric == lexical here, but confirms
    # the parsed-int sort path).
    proj = _project_with_sprints(tmp_path, ["001-a", "002-b", "010-c"])
    p = _active_sprint_path(proj)
    assert p is not None and p.name == "010-c"


# ---------------------------------------------------------------------------
# patterns — word-boundary slug + single-pass matcher
# ---------------------------------------------------------------------------


def test_matched_slugs_single_pass_word_boundary(tmp_path: Path) -> None:
    from socrates120x.patterns import _matched_slugs_in_project, _slug_in_project

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.md").write_text("we used validate-numbers and the author wrote it", encoding="utf-8")
    slugs = ["validate-numbers", "auth", "ingest"]
    matched = _matched_slugs_in_project(slugs, proj)
    assert matched == ["validate-numbers"]  # 'auth' must not match 'author'
    # input ordering preserved
    assert _slug_in_project("validate-numbers", proj) is True
    assert _slug_in_project("auth", proj) is False


def test_matched_slugs_orders_by_input(tmp_path: Path) -> None:
    from socrates120x.patterns import _matched_slugs_in_project

    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "x.md").write_text("ingest scope-data validate", encoding="utf-8")
    assert _matched_slugs_in_project(["validate", "ingest", "scope-data"], proj) == [
        "validate",
        "ingest",
        "scope-data",
    ]


# ---------------------------------------------------------------------------
# decide — multi-line text collapses to a single bullet
# ---------------------------------------------------------------------------


def test_decide_collapses_multiline_to_single_bullet(tmp_path: Path) -> None:
    from socrates120x.decide import record_decision

    planning = tmp_path / "planning"
    planning.mkdir(parents=True)
    (planning / "DECISIONS.md").write_text(
        "# DECISIONS\n\n## Explicitly out of scope\n\n- nothing\n", encoding="utf-8"
    )
    rc = record_decision(tmp_path, "line one\nline two\n\tindented")
    assert rc == 0
    body = (planning / "DECISIONS.md").read_text(encoding="utf-8")
    assert "- **line one line two indented (" in body
    # The bullet stays on one line (closing ** not orphaned).
    bullet_line = next(ln for ln in body.splitlines() if "line one line two" in ln)
    assert bullet_line.rstrip().endswith(")**")


# ---------------------------------------------------------------------------
# timeline — decision date anchored at end of bullet
# ---------------------------------------------------------------------------


def test_timeline_decision_date_anchored_at_end(tmp_path: Path) -> None:
    from socrates120x.timeline import EventKind, build_timeline

    planning = tmp_path / "planning"
    planning.mkdir(parents=True)
    (planning / "DECISIONS.md").write_text(
        "# DECISIONS\n\n## Decisions captured\n\n"
        "- **Migrate by (2024-12-31) (2026-05-20)**\n",
        encoding="utf-8",
    )
    events = [e for e in build_timeline(tmp_path) if e.kind is EventKind.DECISION]
    assert len(events) == 1
    # The trailing stamp (2026-05-20) is the recording date, not the body date.
    assert events[0].date == _dt.date(2026, 5, 20)
    # The body date is preserved in the rendered title.
    assert "(2024-12-31)" in events[0].title


# ---------------------------------------------------------------------------
# journal — only YYYY-MM-DD.md files are entries
# ---------------------------------------------------------------------------


def test_journal_list_ignores_non_dated_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from socrates120x.journal import create_or_open_entry

    journal = tmp_path / "planning" / "journal"
    journal.mkdir(parents=True)
    (journal / "2026-06-16.md").write_text("entry", encoding="utf-8")
    (journal / "notes.md").write_text("not an entry", encoding="utf-8")
    (journal / "README.md").write_text("readme", encoding="utf-8")
    assert create_or_open_entry(tmp_path, list_all=True) == 0
    out = capsys.readouterr().out
    assert "2026-06-16" in out
    assert "notes" not in out
    assert "README" not in out


# ---------------------------------------------------------------------------
# scaffold / companyos — reject a regular-file target
# ---------------------------------------------------------------------------


def test_scaffold_rejects_regular_file_target(tmp_path: Path) -> None:
    from socrates120x.companyos import scaffold_companyos
    from socrates120x.scaffold import scaffold

    f = tmp_path / "afile"
    f.write_text("i am a file", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        scaffold(f)
    with pytest.raises(NotADirectoryError):
        scaffold_companyos(f)


# ---------------------------------------------------------------------------
# cli — slug safety (path traversal / absolute / separators)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "..", ".", "../escape", "a/b", "a\\b", "/etc/passwd", "x\x00y"],
)
def test_validate_slug_rejects_unsafe(bad: str) -> None:
    from socrates120x.cli import _validate_slug

    assert _validate_slug(bad) is not None


@pytest.mark.parametrize("ok", ["quarterly-rebates", "v0.8.0", ".hidden", "proj_1"])
def test_validate_slug_accepts_safe(ok: str) -> None:
    from socrates120x.cli import _validate_slug

    assert _validate_slug(ok) is None


# ---------------------------------------------------------------------------
# ship — dead state_next/json block removed
# ---------------------------------------------------------------------------


def test_ship_module_no_longer_imports_json() -> None:
    import socrates120x.ship as ship

    # The only json use was the dead state_next `pass` block; it's gone.
    assert not hasattr(ship, "json")


# ---------------------------------------------------------------------------
# pack — HTML output carries a strict CSP
# ---------------------------------------------------------------------------


def test_pack_html_has_strict_csp(tmp_path: Path) -> None:
    pytest.importorskip("markdown")
    from socrates120x.pack import build_pack

    (tmp_path / "planning").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("# router", encoding="utf-8")
    html = build_pack(tmp_path, format="html")
    assert "Content-Security-Policy" in html
    assert "script-src 'none'" in html
