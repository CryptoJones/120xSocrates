"""Test the interview runner with scripted input."""

from __future__ import annotations

from pathlib import Path

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
