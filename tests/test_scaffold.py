from pathlib import Path

import pytest

from socrates120x import PROJECT_DIRS, PROJECT_FILES, scaffold


def test_scaffold_creates_full_tree(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    written = scaffold(target)

    assert target.is_dir()
    for d in PROJECT_DIRS:
        assert (target / d).is_dir(), f"missing dir: {d}"
    for f in PROJECT_FILES:
        assert (target / f).is_file(), f"missing file: {f}"
    assert len(written) == len(PROJECT_FILES)


def test_scaffold_refuses_to_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    with pytest.raises(FileExistsError):
        scaffold(target)


def test_scaffold_overwrite_flag_allows_reentry(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    scaffold(target)
    # Second call with overwrite=True must not raise.
    scaffold(target, overwrite=True)
    for f in PROJECT_FILES:
        assert (target / f).is_file()


# ---------------------------------------------------------------------------
# Target-is-a-file rejection
# (validation/scaffold-rejects-file-target)
# ---------------------------------------------------------------------------


def test_scaffold_rejects_file_target_with_clear_message(tmp_path) -> None:
    """If the operator passes a path that is an existing regular file,
    fail up-front with NotADirectoryError, not a confusing mid-scaffold
    error from inside the directory-creation loop."""
    import pytest

    from socrates120x import scaffold

    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("hi", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="regular file"):
        scaffold(file_path)
    # And nothing got created next to it.
    assert not (file_path.parent / "not-a-dir.txt" / "planning").exists()


def test_scaffold_overwrite_true_still_rejects_file_target(tmp_path) -> None:
    """overwrite=True is for replacing an EMPTY directory; it must NOT
    silently overwrite a regular file (which would be data loss)."""
    import pytest

    from socrates120x import scaffold

    file_path = tmp_path / "important.txt"
    file_path.write_text("user content I would hate to lose", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        scaffold(file_path, overwrite=True)
    # File must be untouched.
    assert file_path.read_text(encoding="utf-8") == "user content I would hate to lose"
