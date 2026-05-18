from pathlib import Path

import pytest

from socrates120x.scaffold import DIRS, FILES, scaffold


def test_scaffold_creates_full_tree(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    written = scaffold(target)

    assert target.is_dir()
    for d in DIRS:
        assert (target / d).is_dir(), f"missing dir: {d}"
    for f in FILES:
        assert (target / f).is_file(), f"missing file: {f}"
    assert len(written) == len(FILES)


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
    for f in FILES:
        assert (target / f).is_file()
