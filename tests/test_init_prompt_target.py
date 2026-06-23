"""Tests for `socrates init` prompting for the project folder location/name.

When the project slug is omitted on the command line, init asks the operator
two things: where the new folder should live and what it should be called.
These tests pin that prompting (`_prompt_for_target`) and the dispatch glue
that requires a TTY when no slug is given.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x import _prompt_for_target, main


def _input_sequence(answers: list[str]):
    """Return an input() stand-in that yields each answer in turn, raising
    EOFError once exhausted (mirrors a closed stdin)."""
    it = iter(answers)

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration as exc:
            raise EOFError from exc

    return fake_input


def test_prompt_returns_given_base_and_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "somewhere"
    monkeypatch.setattr(
        "builtins.input", _input_sequence([str(dest), "my-project"])
    )
    base, slug = _prompt_for_target(default_base=tmp_path)
    assert base == dest
    assert slug == "my-project"


def test_prompt_blank_location_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", _input_sequence(["", "thing"]))
    base, slug = _prompt_for_target(default_base=tmp_path)
    assert base == tmp_path
    assert slug == "thing"


def test_prompt_reprompts_on_empty_then_invalid_then_valid_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # blank name -> rejected, traversal name -> rejected, then a good one.
    monkeypatch.setattr(
        "builtins.input",
        _input_sequence(["", "", "../escape", "good-name"]),
    )
    base, slug = _prompt_for_target(default_base=tmp_path)
    assert base == tmp_path
    assert slug == "good-name"
    out = capsys.readouterr().out
    assert "required" in out
    assert ".." in out  # the validation error for the traversal attempt


def test_prompt_abort_on_eof_returns_none_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Operator hits the location prompt then closes stdin (Ctrl-D).
    monkeypatch.setattr("builtins.input", _input_sequence([str(tmp_path)]))
    base, slug = _prompt_for_target(default_base=tmp_path)
    assert slug is None


def test_init_without_slug_needs_a_tty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No slug + no TTY = a clean error, not a hang waiting on input()."""
    monkeypatch.setattr("socrates120x.cli.is_interactive", lambda: False)
    rc = main(["init", "--base", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "interactive terminal" in err or "project slug" in err
