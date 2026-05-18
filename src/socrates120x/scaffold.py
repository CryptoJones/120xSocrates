"""Create the canonical 120x Operators Kit folder structure.

Mirrors the kit's scaffold.sh so socrates is self-contained.
"""

from __future__ import annotations

from pathlib import Path

DIRS: tuple[str, ...] = (
    "docs",
    "planning",
    "planning/journal",
    "planning/meetings",
    "planning/sprints/001-discovery-architecture",
    "src",
    "tests",
    "scripts",
    "samples",
    "references",
)

# Files to create empty. socrates will populate most of these afterwards.
FILES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "README.md",
    ".gitignore",
    "docs/ARCHITECTURE.md",
    "docs/DATA_MODEL.md",
    "docs/API.md",
    "docs/PERMISSIONS.md",
    "docs/VALIDATION.md",
    "planning/STATE.md",
    "planning/DECISIONS.md",
    "planning/DOMAIN.md",
    "planning/RISKS.md",
    "planning/QUESTIONS.md",
    "planning/FILE_INVENTORY.md",
    "planning/journal/README.md",
    "planning/meetings/README.md",
    "planning/sprints/001-discovery-architecture/requirements.md",
    "planning/sprints/001-discovery-architecture/blueprint.md",
    "planning/sprints/001-discovery-architecture/acceptance.md",
    "planning/sprints/001-discovery-architecture/handoff-prompt.md",
    "src/README.md",
    "tests/README.md",
    "scripts/README.md",
    "samples/README.md",
    "references/README.md",
)


def scaffold(target: Path, *, overwrite: bool = False) -> list[Path]:
    """Create the 120x folder/file tree at *target*.

    Returns the list of files created (or that already existed).
    Raises FileExistsError if *target* already exists and ``overwrite`` is False.
    """
    if target.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing path: {target}")

    target.mkdir(parents=True, exist_ok=overwrite)
    for d in DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    for f in FILES:
        path = target / f
        if not path.exists():
            path.touch()
        created.append(path)
    return created
