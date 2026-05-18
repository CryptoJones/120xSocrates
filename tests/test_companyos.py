"""Tests for the CompanyOS scaffold."""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x.companyos import DIRS, scaffold_companyos


def test_companyos_scaffold_creates_full_macro_tree(tmp_path: Path) -> None:
    target = tmp_path / "120x"
    written = scaffold_companyos(target)

    assert target.is_dir()
    for d in DIRS:
        assert (target / d).is_dir(), f"missing dir: {d}"
    # Spot check: every dir has at least a README.md.
    for d in DIRS:
        assert (target / d / "README.md").is_file(), f"missing README.md in {d}"
    assert (target / "AGENTS.md").is_file()
    assert (target / "CLAUDE.md").is_file()
    assert (target / "CODEX.md").is_file()
    assert (target / "README.md").is_file()
    assert len(written) >= 10


def test_companyos_agents_md_routes_to_builds(tmp_path: Path) -> None:
    target = tmp_path / "120x"
    scaffold_companyos(target)
    agents = (target / "AGENTS.md").read_text()
    assert "builds/" in agents
    assert "patterns/" in agents
    assert "clients/" in agents


def test_companyos_refuses_to_overwrite_non_empty(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    (target / "junk.txt").write_text("something")
    with pytest.raises(FileExistsError):
        scaffold_companyos(target)


def test_companyos_allows_empty_dir(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    # Should succeed against an empty pre-existing dir.
    scaffold_companyos(target)
    assert (target / "AGENTS.md").is_file()
