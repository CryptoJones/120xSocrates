"""Test the interview runner with scripted input."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from socrates120x.interview import QUESTIONS, Interview


class _FakeIO:
    """Scripted stdin/stdout for the interview."""

    def __init__(self, lines: list[str]) -> None:
        self._iter = iter(lines)
        self.output: list[str] = []

    def input_fn(self, prompt: str = "") -> str:
        self.output.append(prompt)
        try:
            return next(self._iter)
        except StopIteration:
            raise EOFError from None

    def output_fn(self, msg: str = "") -> None:
        self.output.append(msg)


def _answers_for_full_interview() -> list[str]:
    """Build a scripted answer stream for every question in QUESTIONS."""
    answers: list[str] = []
    for q in QUESTIONS:
        if q.type == "line":
            answers.append("answer for " + q.key if q.required else q.default or "x")
        elif q.type == "multiline":
            answers.append("first line for " + q.key)
            answers.append("second line")
            answers.append(".")
        elif q.type == "list":
            answers.append("item one for " + q.key)
            answers.append("item two for " + q.key)
            answers.append("")  # terminator
    return answers


def test_interview_records_all_questions(tmp_path: Path) -> None:
    answers_path = tmp_path / ".socrates-answers.json"
    iv = Interview(answers_path=answers_path, project_name="demo")
    io = _FakeIO(_answers_for_full_interview())
    iv.run(input_fn=io.input_fn, output_fn=io.output_fn)

    assert iv.answers["project_name"] == "demo"
    for q in QUESTIONS:
        assert q.key in iv.answers, f"missing answer for {q.key}"


def test_interview_saves_incrementally(tmp_path: Path) -> None:
    answers_path = tmp_path / ".socrates-answers.json"
    iv = Interview(answers_path=answers_path, project_name="demo")
    io = _FakeIO(_answers_for_full_interview())
    iv.run(input_fn=io.input_fn, output_fn=io.output_fn)

    # Answer file exists and is non-empty after the run.
    assert answers_path.exists()
    text = answers_path.read_text()
    assert "demo" in text
    assert text.startswith("{")


def test_list_prompts_show_running_count(tmp_path: Path) -> None:
    """After each list item, the interview should print a running confirmation."""
    answers_path = tmp_path / ".socrates-answers.json"
    iv = Interview(answers_path=answers_path, project_name="demo")
    io = _FakeIO(_answers_for_full_interview())
    iv.run(input_fn=io.input_fn, output_fn=io.output_fn)

    transcript = "\n".join(io.output)
    # Each list answer adds two items; the confirmation should appear at least
    # once per list question.
    assert "✓ (1 so far)" in transcript
    assert "✓ (2 so far)" in transcript
    assert "captured" in transcript


def test_editor_mode_uses_subprocess(tmp_path: Path) -> None:
    """With editor=True, multi-line questions invoke $EDITOR via subprocess.run."""

    def fake_editor_run(cmd: list[str], check: bool = True) -> Any:  # noqa: ARG001
        # cmd is [editor, tmpfile_path]. Write a fake user answer to the file.
        target = Path(cmd[-1])
        target.write_text(
            "# this line is a comment and should be stripped\n"
            "real answer line one\n"
            "real answer line two\n"
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    answers_path = tmp_path / ".socrates-answers.json"
    iv = Interview(answers_path=answers_path, project_name="demo", editor=True)

    # Stream just enough single-line / list answers; multiline ones are handled
    # by the patched subprocess.run, so they consume zero lines from the stream.
    answers: list[str] = []
    for q in QUESTIONS:
        if q.type == "line":
            answers.append("x" if q.required else q.default or "x")
        elif q.type == "list":
            answers.extend(["item-a", "item-b", ""])
        # multiline questions go through the editor, consume no scripted input
    io = _FakeIO(answers)

    with (
        patch.object(subprocess, "run", side_effect=fake_editor_run),
        patch.dict(os.environ, {"EDITOR": "fake-editor"}),
    ):
        iv.run(input_fn=io.input_fn, output_fn=io.output_fn)

    # business_goal is a multiline required question — should have come from the editor.
    assert iv.answers["business_goal"] == "real answer line one\nreal answer line two"
