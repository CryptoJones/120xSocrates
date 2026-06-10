"""Slug-safety tests for `socrates init <slug>`.

The slug is appended to --base to form the target directory. Without
validation:
- absolute slugs (e.g. /etc/passwd) replace the base entirely (Python
  pathlib: Path("base") / "/etc/passwd" -> "/etc/passwd").
- slugs containing / or \\ nest unexpectedly or escape via ..
- empty slug resolves to the base dir itself, risking damage to siblings.

These tests pin the validation behavior added to _validate_slug.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x import _validate_slug, main


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "   ",
        "/etc/passwd",
        "/tmp/abs",
        "foo/bar",
        "foo\\bar",
        "..",
        ".",
        "../../tmp/bad",
        "valid/with/sep",
        "with\x00null",
    ],
)
def test_validate_slug_rejects_unsafe(slug: str) -> None:
    assert _validate_slug(slug) is not None, f"slug {slug!r} should be rejected"


@pytest.mark.parametrize(
    "slug",
    [
        "quarterly-rebates",
        "my_project",
        "PROJECT123",
        "v0.8.0",
        ".hidden",
        "a-b-c-d",
        "x",
    ],
)
def test_validate_slug_accepts_safe(slug: str) -> None:
    assert _validate_slug(slug) is None, f"slug {slug!r} should be accepted"


def test_init_rejects_absolute_slug_before_scaffold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: `socrates init /etc/passwd --base <tmp>` must error out
    BEFORE touching the filesystem at /etc/passwd."""
    base = tmp_path / "base"
    base.mkdir()
    argv = ["init", "/etc/passwd", "--base", str(base)]
    rc = main(argv)
    assert rc == 2
    err = capsys.readouterr().err
    # Any rejection message is fine — the load-bearing assertion is that the
    # filesystem stayed clean. Validator order may catch this as either
    # "absolute" or "contains /"; either is acceptable.
    assert "error:" in err
    # Most importantly: /etc/passwd/docs etc. must not have been created.
    assert not (Path("/etc/passwd/docs")).exists()


def test_init_rejects_traversal_slug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "base"
    base.mkdir()
    sibling = tmp_path / "escape-target"
    rc = main(["init", "../escape-target", "--base", str(base)])
    assert rc == 2
    err = capsys.readouterr().err
    assert ".." in err
    # The escape target must not have been created either.
    assert not sibling.exists()


def test_init_rejects_nested_slug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "base"
    base.mkdir()
    rc = main(["init", "a/b", "--base", str(base)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "single path component" in err


def test_init_rejects_empty_slug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "base"
    base.mkdir()
    rc = main(["init", "", "--base", str(base)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "empty" in err
