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


def test_companyos_rejects_file_target(tmp_path) -> None:
    """Symmetric guard with scaffold(): passing a regular file path must
    fail up-front, not midway through the per-file write loop."""
    import pytest

    from socrates120x.companyos import scaffold_companyos

    file_path = tmp_path / "co.txt"
    file_path.write_text("operator's notes", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="regular file"):
        scaffold_companyos(file_path)
    assert file_path.read_text(encoding="utf-8") == "operator's notes"


def test_cli_companyos_handles_file_target_gracefully(tmp_path, capsys) -> None:
    """CLI entry point must catch NotADirectoryError too, not just FileExistsError.
    Pre-fix the new validation in scaffold_companyos crashed the CLI with a
    stacktrace because _cmd_companyos only caught FileExistsError."""
    from socrates120x.cli import main

    file_path = tmp_path / "operators-notes.txt"
    file_path.write_text("user content", encoding="utf-8")
    rc = main(["companyos", str(file_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    # The actual file content is untouched.
    assert file_path.read_text(encoding="utf-8") == "user content"
