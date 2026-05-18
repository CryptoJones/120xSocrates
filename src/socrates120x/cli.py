"""Command-line entrypoint for 120xSocrates.

Subcommands:

- `socrates init <slug>`    — scaffold a project and run the Socratic interview
- `socrates audit [path]`   — verify the planning files of an existing project
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from socrates120x import __version__
from socrates120x.audit import format_report, run_audit
from socrates120x.audit.model import Severity
from socrates120x.interview import Interview, is_interactive
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="socrates",
        description=(
            "120xSocrates — tooling on top of the 120x Operators Kit. "
            "Scaffold + interview a new project, or audit an existing one."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser(
        "init",
        help="Scaffold a project and run the Socratic interview.",
        description="Create the 120x folder tree and interview the operator to populate it.",
    )
    init.add_argument(
        "project",
        help="Project slug (e.g. 'quarterly-rebates'). Becomes a folder under --base.",
    )
    init.add_argument(
        "--base", type=Path, default=Path.cwd(),
        help="Parent directory in which to create the project folder. Default: cwd.",
    )
    init.add_argument(
        "--no-scaffold", action="store_true",
        help="Skip the scaffold step. Use when the project folder already exists.",
    )
    init.add_argument(
        "--resume", action="store_true",
        help="Resume a partially-completed interview from .socrates-answers.json.",
    )
    init.add_argument(
        "--no-render", action="store_true",
        help="Save answers but do NOT write the .md files yet.",
    )
    init.add_argument(
        "--editor", action="store_true",
        help="For multi-line questions, open $EDITOR instead of prompting line-by-line.",
    )

    audit = sub.add_parser(
        "audit",
        help="Verify the planning files of a 120x project for internal consistency.",
        description=(
            "Scan a 120x project for missing files, broken sprint folders, weasel "
            "words in acceptance criteria, stale STATE, etc. Exits non-zero on errors."
        ),
    )
    audit.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder to audit. Default: current working directory.",
    )
    audit.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as errors when computing the exit code.",
    )
    audit.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )

    args = parser.parse_args(argv)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "audit":
        return _cmd_audit(args)
    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


# ---------------------------------------------------------------------------
# `init` subcommand
# ---------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace) -> int:
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
        editor=args.editor,
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
    print(f"  4. When the planning is settled, run: socrates audit {target}")
    print()
    print("The handoff is a folder, not a conversation.")
    print()


# ---------------------------------------------------------------------------
# `audit` subcommand
# ---------------------------------------------------------------------------


def _cmd_audit(args: argparse.Namespace) -> int:
    path: Path = args.path.expanduser().resolve()
    if not path.is_dir():
        print(f"error: {path} is not a directory", file=sys.stderr)
        return 2

    report = run_audit(path)
    output = format_report(report, as_json=args.json)
    print(output)

    has_errors = any(f.severity is Severity.ERROR for f in report.findings)
    has_warnings = any(f.severity is Severity.WARNING for f in report.findings)
    if has_errors:
        return 1
    if has_warnings and args.strict:
        return 1
    return 0
