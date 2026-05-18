"""Smoke tests for the prompting primitives."""

from __future__ import annotations

import os
from unittest.mock import patch

from socrates120x.prompting import Question, ask, editor_command


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
