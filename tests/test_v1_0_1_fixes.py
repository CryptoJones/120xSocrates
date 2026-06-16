"""Regression tests for the two v1.0.1 fixes.

Both live in modules the v1.0.0 review wave touched, but no prior branch
covered either: the EOF abort in the interactive prompts, and word-boundary
matching in the acceptance-weasels audit check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x import Question, check_acceptance_weasels
from socrates120x.interview import Interview
from socrates120x.support import _ask_line, _ask_multiline


def _dead_input(_prompt: str) -> str:
    raise EOFError


# ---------------------------------------------------------------------------
# EOF on an exhausted stream must abort, not spin/recurse
# ---------------------------------------------------------------------------


def test_ask_line_required_no_default_raises_on_eof() -> None:
    q = Question(key="client", prompt="?", section="x", required=True)
    # Old behavior: set raw="" then `continue` → infinite CPU spin. Now: re-raise.
    with pytest.raises(EOFError):
        _ask_line(_dead_input, lambda _s: None, q)


def test_ask_line_uses_default_on_eof() -> None:
    q = Question(key="tech", prompt="?", section="x", default="TBD")
    assert _ask_line(_dead_input, lambda _s: None, q) == "TBD"


def test_ask_line_optional_returns_empty_on_eof() -> None:
    q = Question(key="x", prompt="?", section="x")  # not required, no default
    assert _ask_line(_dead_input, lambda _s: None, q) == ""


def test_ask_multiline_required_raises_on_eof_not_recursionerror() -> None:
    q = Question(key="goal", prompt="?", section="x", type="multiline", required=True)
    with pytest.raises(EOFError):
        _ask_multiline(_dead_input, lambda _s: None, q)


def test_interview_run_aborts_cleanly_on_exhausted_stdin(tmp_path: Path) -> None:
    iv = Interview(answers_path=tmp_path / ".socrates-answers.json", project_name="p")
    # First init question (`client`) is required with no default; a dead stream
    # must surface EOFError (which cli/extract catch) rather than hang.
    with pytest.raises(EOFError):
        iv.run(input_fn=_dead_input, output_fn=lambda _s: None)


# ---------------------------------------------------------------------------
# acceptance-weasels: word boundaries, not substrings
# ---------------------------------------------------------------------------


def _project_with_acceptance(tmp_path: Path, body: str) -> Path:
    sprint = tmp_path / "planning" / "sprints" / "001-x"
    sprint.mkdir(parents=True)
    (sprint / "acceptance.md").write_text(body, encoding="utf-8")
    return tmp_path


def test_weasel_no_false_positive_on_substrings(tmp_path: Path) -> None:
    proj = _project_with_acceptance(
        tmp_path,
        "# acceptance\n- STBD pin connector is seated\n- has needed review\n",
    )
    assert check_acceptance_weasels(proj) == []


def test_weasel_still_flags_real_weasels(tmp_path: Path) -> None:
    proj = _project_with_acceptance(
        tmp_path, "# acceptance\n- behavior is TBD\n- handle edge cases etc.\n"
    )
    msgs = [f.message for f in check_acceptance_weasels(proj)]
    assert any("TBD" in m for m in msgs)
    assert any("etc." in m for m in msgs)
