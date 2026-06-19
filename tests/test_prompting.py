"""Smoke tests for the prompting primitives."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from socrates120x import Question, ask, editor_command
from socrates120x.support import _ask_multiline_editor


class _FakeIO:
    def __init__(self, lines: list[str]) -> None:
        self._iter = iter(lines)
        self.output: list[str] = []

    def input_fn(self, prompt: str = "") -> str:
        self.output.append(prompt)
        return next(self._iter)

    def output_fn(self, msg: str = "") -> None:
        self.output.append(msg)


def test_ask_line_returns_input() -> None:
    io = _FakeIO(["my answer"])
    q = Question(key="x", prompt="?", section="s")
    result = ask(q, 1, 1, io.input_fn, io.output_fn)
    assert result == "my answer"


def test_ask_line_uses_default_on_empty() -> None:
    io = _FakeIO([""])
    q = Question(key="x", prompt="?", section="s", default="fallback")
    result = ask(q, 1, 1, io.input_fn, io.output_fn)
    assert result == "fallback"


def test_ask_list_returns_items() -> None:
    io = _FakeIO(["one", "two", "three", ""])
    q = Question(key="x", prompt="?", section="s", type="list")
    result = ask(q, 1, 1, io.input_fn, io.output_fn)
    assert result == ["one", "two", "three"]


def test_ask_multiline_terminated_by_dot() -> None:
    io = _FakeIO(["line one", "line two", "."])
    q = Question(key="x", prompt="?", section="s", type="multiline")
    result = ask(q, 1, 1, io.input_fn, io.output_fn)
    assert result == "line one\nline two"


def test_editor_command_honours_env() -> None:
    with patch.dict(os.environ, {"EDITOR": "myeditor --flag"}, clear=False):
        # VISUAL is checked first, so unset it.
        os.environ.pop("VISUAL", None)
        assert editor_command() == ["myeditor", "--flag"]


def test_editor_command_falls_back_when_unset() -> None:
    with patch.dict(os.environ, {}, clear=True):
        # Either resolves to a system fallback (nano/vim/vi) or None — both are valid.
        cmd = editor_command()
        if cmd is not None:
            assert cmd[0] in ("nano", "vim", "vi")


# ---------------------------------------------------------------------------
# editor_command — shlex parsing of $EDITOR
# (bugfix/prompting-shlex-and-input-fn)
# ---------------------------------------------------------------------------


def test_editor_command_parses_quoted_args(monkeypatch) -> None:
    """`EDITOR="emacsclient -a 'emacs'"` must split to 3 elements, not 3
    elements where the last has stray quotes."""
    from socrates120x import editor_command
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "emacsclient -a 'emacs'")
    cmd = editor_command()
    assert cmd == ["emacsclient", "-a", "emacs"], (
        f"expected shlex-parsed args; got {cmd!r}. "
        "Naive str.split leaves stray quotes attached to 'emacs'."
    )


def test_editor_command_handles_double_quoted_path(monkeypatch) -> None:
    """A path with spaces wrapped in double quotes must survive."""
    from socrates120x import editor_command
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", '"C:/Program Files/Editor/run.exe" --wait')
    cmd = editor_command()
    assert cmd == ["C:/Program Files/Editor/run.exe", "--wait"]


def test_editor_command_recovers_from_unbalanced_quotes(monkeypatch) -> None:
    """A malformed EDITOR string (unbalanced quote) shouldn't crash —
    fall back to naive split rather than returning None silently."""
    from socrates120x import editor_command
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "broken 'arg")
    cmd = editor_command()
    assert cmd is not None
    assert "broken" in cmd


# ---------------------------------------------------------------------------
# editor path failure handling (#28, #29)
# ---------------------------------------------------------------------------


def test_editor_failure_falls_back_to_inline(monkeypatch) -> None:
    # Regression (#28): a non-zero editor exit (CalledProcessError) used to
    # escape both interview handlers and dump a traceback. Now it falls back
    # to the inline prompt instead.
    monkeypatch.setattr("socrates120x.support.editor_command", lambda: ["fakeeditor"])

    def boom(*_a, **_k):
        raise subprocess.CalledProcessError(1, "fakeeditor")

    monkeypatch.setattr("socrates120x.support.subprocess.run", boom)
    io = _FakeIO(["typed inline", "."])
    q = Question(key="x", prompt="?", section="s", type="multiline")
    result = _ask_multiline_editor(io.output_fn, q, input_fn=io.input_fn)
    assert result == "typed inline"


def test_editor_required_empty_aborts_after_cap(monkeypatch) -> None:
    # Regression (#29): a required field that stays empty across the editor
    # retry cap must abort (EOFError) rather than silently storing "".
    monkeypatch.setattr("socrates120x.support.editor_command", lambda: ["fakeeditor"])
    # No-op editor leaves only the comment header → empty body every time.
    monkeypatch.setattr("socrates120x.support.subprocess.run", lambda *_a, **_k: None)
    io = _FakeIO([])
    q = Question(key="x", prompt="?", section="s", type="multiline", required=True)
    with pytest.raises(EOFError):
        _ask_multiline_editor(io.output_fn, q, input_fn=io.input_fn)
