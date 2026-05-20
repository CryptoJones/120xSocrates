"""The `socrates extract` subcommand — capture a reusable pattern at sprint close.

The 120x philosophy promises three assets per project: the shipped system,
the preserved blueprint, and the extracted pattern. The third is the one
that compounds across engagements, and it is the one most often skipped.
This module makes it cheap.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

from socrates120x.interview import Interview, Question

PATTERN_QUESTIONS: tuple[Question, ...] = (
    Question(
        key="pattern_focus",
        prompt=(
            "Look back at this sprint. What is the single most useful thing it "
            "produced that you would re-use on a future project?"
        ),
        section="Pattern",
        type="multiline",
        help=(
            "Free text. Not a feature — a *pattern*. An approach, a piece of code, "
            "a prompt, a piece of scoping language, a workflow."
        ),
        required=True,
    ),
    Question(
        key="pattern_kind",
        prompt="What kind of artifact is it? (one short label)",
        section="Pattern",
        help=(
            "Examples: architecture-pattern, data-ingestion, validation-approach, "
            "prompt-template, scoping-language, pricing-pattern, client-comms, "
            "test-harness, parser, debugging-recipe."
        ),
        required=True,
    ),
    Question(
        key="pattern_slug",
        prompt="Name it as a short kebab-case <verb>-<noun> slug.",
        section="Pattern",
        help=(
            'Examples: validate-parsed-numbers, scope-data-projects, '
            'ingest-vendor-spreadsheets, price-internal-tools.'
        ),
        required=True,
    ),
    Question(
        key="pattern_summary",
        prompt="One sentence — what does it do?",
        section="Pattern",
        required=True,
    ),
    Question(
        key="pattern_when_applies",
        prompt="When does this pattern apply? (the trigger situation)",
        section="Applicability",
        type="multiline",
        help="Be concrete. 'When the client gives you weekly vendor spreadsheets', not 'when there is data'.",
        required=True,
    ),
    Question(
        key="pattern_when_does_not",
        prompt="When does this pattern NOT apply? (where it would break)",
        section="Applicability",
        type="multiline",
        help=(
            "Patterns that don't list their failure modes get cargo-culted. "
            "What kind of project should NOT use this?"
        ),
    ),
    Question(
        key="pattern_body",
        prompt="The pattern itself — paste the code, prompt, template, or sketch.",
        section="Body",
        type="multiline",
        help=(
            "This is the load-bearing field. Be specific enough that you could "
            "drop it into the next project unchanged. --editor mode is recommended."
        ),
        required=True,
    ),
    Question(
        key="pattern_war_story",
        prompt="What about this project taught you this pattern? (the war story)",
        section="Provenance",
        type="multiline",
        help=(
            "The story of how you discovered or earned this pattern. Important "
            "because it grounds the pattern in a real situation, not a theory."
        ),
    ),
    Question(
        key="pattern_confidence",
        prompt="Confidence level — 1 (rough draft) to 5 (battle-tested across many projects).",
        section="Provenance",
        help="A fresh extraction is usually 1 or 2.",
        default="1",
    ),
)


def run_extract(
    project: Path,
    *,
    patterns_dir: Path | None = None,
    resume: bool = False,
    editor: bool = False,
) -> tuple[int, Path | None]:
    """Run the extraction interview and write a pattern candidate.

    Returns (exit_code, path_to_pattern_file).
    """
    target_dir = patterns_dir or _resolve_patterns_dir(project)
    target_dir.mkdir(parents=True, exist_ok=True)

    answers_path = project / ".socrates-extract-answers.json"
    iv = Interview(
        answers_path=answers_path,
        resume=resume,
        editor=editor,
        questions=PATTERN_QUESTIONS,
    )
    try:
        iv.run()
    except KeyboardInterrupt:
        print(
            "\n\nExtraction interrupted. Answers saved. "
            "Re-run with --resume to pick up where you left off.",
        )
        return 130, None

    slug = _sanitize_slug(iv.answers.get("pattern_slug", "untitled"))
    target = target_dir / f"CANDIDATE-{slug}.md"
    target.write_text(render_pattern(iv.answers, project=project), encoding="utf-8")
    print(f"\nPattern candidate written to: {target}")
    print()
    print("Next steps:")
    print(f"  1. Read {target}.")
    print("  2. Tighten the body. Remove anything that does not generalise.")
    print("  3. When the pattern proves itself on a SECOND project, rename")
    print(f"     CANDIDATE-{slug}.md → {slug}.md to promote it.")
    return 0, target


def render_pattern(answers: dict[str, Any], *, project: Path) -> str:
    today = _dt.date.today().isoformat()
    summary = answers.get("pattern_summary") or "_(untitled pattern)_"
    kind = answers.get("pattern_kind") or "_(unclassified)_"
    confidence = answers.get("pattern_confidence") or "1"
    when_applies = answers.get("pattern_when_applies") or "_(not specified)_"
    when_does_not = answers.get("pattern_when_does_not") or "_(not specified)_"
    body = answers.get("pattern_body") or "_(not yet captured)_"
    war_story = answers.get("pattern_war_story") or "_(not captured)_"
    focus = answers.get("pattern_focus") or ""

    return f"""# Pattern: {answers.get("pattern_slug", "untitled")} (CANDIDATE)

> {summary}

| | |
|---|---|
| **Kind** | {kind} |
| **Confidence** | {confidence} / 5 |
| **Extracted** | {today} |
| **Source project** | `{project.name}` |

## When this applies

{when_applies}

## When it does NOT apply

{when_does_not}

## The pattern

{body}

## Why this pattern exists (the war story)

{war_story}

## Original focus (operator's own words at extraction time)

{focus}

---

_This is a CANDIDATE pattern — it has been observed once. Promote to a real pattern (drop the `CANDIDATE-` prefix) only after it has worked on at least one additional project._
"""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_patterns_dir(project: Path) -> Path:
    """Find the patterns/ directory.

    If *project* is inside a CompanyOS layout (i.e. it sits inside a
    `builds/` directory that has a sibling `patterns/`), use that. Otherwise
    fall back to ``project/patterns/``.
    """
    parent = project.parent
    if parent.name == "builds":
        candidate = parent.parent / "patterns"
        if candidate.is_dir() or (parent.parent / "AGENTS.md").exists():
            return candidate
    return project / "patterns"


_SLUG = re.compile(r"[^a-z0-9-]")


def _sanitize_slug(raw: str) -> str:
    slug = raw.strip().lower().replace(" ", "-").replace("_", "-")
    slug = _SLUG.sub("", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"
