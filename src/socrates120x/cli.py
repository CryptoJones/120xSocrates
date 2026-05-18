"""Command-line entrypoint for 120xSocrates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from socrates120x import __version__
from socrates120x.interview import Interview, is_interactive
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="socrates",
        description=(
            "120xSocrates — interrogate the operator and populate the planning "
            "files for a 120x Operators Kit project."
        ),
    )
    parser.add_argument(
        "project",
        help=(
            "Project slug (e.g. 'quarterly-rebates'). A folder of this name is "
            "created under --base, or under the current working directory if "
            "--base is omitted."
        ),
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=Path.cwd(),
        help="Parent directory in which to create the project folder. Default: cwd.",
    )
    parser.add_argument(
        "--no-scaffold",
        action="store_true",
        help=(
            "Skip the scaffold step. Use when the project folder already exists "
            "(e.g. from the kit's scaffold.sh)."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an in-progress interview. Loads previously-saved answers "
            "from .socrates-answers.json and lets you keep or change each one."
        ),
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Run the interview and save answers but do NOT write the .md files yet.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args(argv)
    target: Path = args.base.expanduser().resolve() / args.project

    if not args.no_scaffold:
        if target.exists():
            print(
                f"error: {target} already exists. "
                f"Pass --no-scaffold to populate an existing folder, "
                f"or choose a different project slug.",
                file=sys.stderr,
            )
            return 2
        print(f"Scaffolding 120x structure at: {target}")
        scaffold(target)
    else:
        if not target.exists():
            print(
                f"error: {target} does not exist and --no-scaffold was passed.",
                file=sys.stderr,
            )
            return 2
        print(f"Using existing folder: {target}")

    if not is_interactive():
        print(
            "error: socrates needs a TTY for the interview. "
            "Re-run from an interactive terminal.",
            file=sys.stderr,
        )
        return 2

    _print_intro(target.name)
    interview = Interview(
        answers_path=target / ".socrates-answers.json",
        project_name=target.name,
        resume=args.resume,
    )
    try:
        interview.run()
    except KeyboardInterrupt:
        print(
            "\n\nInterview interrupted. Answers so far are saved. "
            "Re-run with --resume to pick up where you left off.",
            file=sys.stderr,
        )
        return 130

    if args.no_render:
        print("\nSkipping render (--no-render). Answers saved.")
        return 0

    written = render_all(target, interview.answers)
    print(f"\nWrote {len(written)} planning files into {target}.")
    _print_outro(target, interview.answers)
    return 0


def _print_intro(project: str) -> None:
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                            120xSocrates                              ║")
    print("║                                                                      ║")
    print("║          Socratic interview for 120x Operators Kit projects          ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"Project: {project}")
    print()
    print("How this works:")
    print("  • You'll be asked ~18 questions, grouped by section.")
    print("  • For multi-line answers, type your text and finish with a single '.'")
    print("  • For list answers, one item per line; empty line to finish.")
    print("  • Press Ctrl-C anytime — your answers are saved; resume with --resume.")
    print()


def _print_outro(target: Path, answers: dict[str, Any]) -> None:
    qs = answers.get("open_questions") or []
    print()
    print("Next steps:")
    print(f"  1. cd {target}")
    print("  2. Review planning/ — push back on anything that does not match reality.")
    if qs:
        print("  3. Send planning/QUESTIONS.md to your Architect (Claude Chat / ChatGPT):")
        for q in qs:
            print(f"       - {q}")
    else:
        print("  3. Open a session with your Architect to draft Sprint 002.")
    print()
    print("The handoff is a folder, not a conversation.")
    print()
