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
from socrates120x.audit import format_report, looks_like_companyos, run_audit
from socrates120x.audit.model import Severity
from socrates120x.companyos import scaffold_companyos
from socrates120x.extract import run_extract
from socrates120x.interview import Interview, is_interactive
from socrates120x.journal import create_or_open_entry
from socrates120x.onboard import synthesize_welcome, write_welcome
from socrates120x.pack import build_pack, write_pack
from socrates120x.patterns import format_pattern_report, review_patterns
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold
from socrates120x.ship import CheckResult, format_preflight, preflight
from socrates120x.status import companyos_status, format_status
from socrates120x.timeline import build_timeline, format_timeline


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

    timeline = sub.add_parser(
        "timeline",
        help="Chronological view of journal entries, sprints, and dated decisions.",
        description=(
            "Build a single chronological feed from planning/journal/, "
            "planning/sprints/, and dated entries in DECISIONS.md. Answers "
            "'what happened on this project, in order?' without scanning git log."
        ),
    )
    timeline.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: cwd.",
    )

    ship = sub.add_parser(
        "ship",
        help="Sprint-close pre-flight: audit + journal + extract + state freshness.",
        description=(
            "Run the four pre-flight checks before declaring a sprint complete. "
            "Composition command — chains existing logic into one ritual. "
            "Exits non-zero if any check fails."
        ),
    )
    ship.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: cwd.",
    )

    pack = sub.add_parser(
        "pack",
        help="Assemble an Architect input bundle (single markdown file).",
        description=(
            "Concatenate AGENTS / STATE / DOMAIN / DECISIONS / RISKS / QUESTIONS "
            "and the active sprint's files into one paste-able markdown bundle "
            "for the Architect (browser chat) session."
        ),
    )
    pack.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: cwd.",
    )
    pack.add_argument(
        "--sprint", type=str, default=None,
        help="Include this sprint folder instead of auto-detecting the highest-numbered one.",
    )
    pack.add_argument(
        "--stdout", action="store_true",
        help="Print to stdout instead of writing .socrates-architect-pack.md.",
    )

    patterns = sub.add_parser(
        "patterns",
        help="Inspect the patterns/ folder for staleness, orphans, and unused candidates.",
        description=(
            "Operates at the CompanyOS root. Scans patterns/ and reports "
            "stale candidates (>90d old), patterns whose source project no "
            "longer exists, and patterns whose slug is not referenced from "
            "any project outside their source — i.e. patterns that have not "
            "yet compounded."
        ),
    )
    patterns_sub = patterns.add_subparsers(dest="patterns_command", required=True)
    patterns_review = patterns_sub.add_parser(
        "review",
        help="Audit the patterns/ folder.",
    )
    patterns_review.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="CompanyOS root. Default: cwd.",
    )

    status = sub.add_parser(
        "status",
        help="One-screen health dashboard for every project in a CompanyOS.",
        description=(
            "Scan every builds/<project>/ under a CompanyOS root and print a "
            "one-line health summary per project: active sprint, audit error "
            "count, days since STATE / journal updates, whether extract has "
            "been run. Designed as the first thing the operator reads each day."
        ),
    )
    status.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="CompanyOS root. Default: cwd.",
    )

    onboard = sub.add_parser(
        "onboard",
        help="Synthesize a 60-second WELCOME.md from the existing planning files.",
        description=(
            "Read STATE / DECISIONS / RISKS / QUESTIONS and write a WELCOME.md "
            "in the project root. Pure synthesis — no interview. Designed for "
            "new humans or agents who need a one-minute briefing."
        ),
    )
    onboard.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: current working directory.",
    )
    onboard.add_argument(
        "--stdout", action="store_true",
        help="Print the synthesized briefing to stdout instead of writing WELCOME.md.",
    )

    extract = sub.add_parser(
        "extract",
        help="Sprint-close interview: capture a reusable pattern from this project.",
        description=(
            "Walk through 9 questions to extract one reusable pattern from the "
            "sprint that just shipped, then write it as patterns/CANDIDATE-<slug>.md. "
            "Run this at the end of every sprint or project — the third deliverable "
            "the 120x methodology promises is the one most often skipped."
        ),
    )
    extract.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: current working directory.",
    )
    extract.add_argument(
        "--patterns-dir", type=Path, default=None,
        help=(
            "Where to write the pattern file. Default: auto-detect (sibling "
            "patterns/ if inside a CompanyOS, else project-local patterns/)."
        ),
    )
    extract.add_argument(
        "--resume", action="store_true",
        help="Resume a partial extraction from .socrates-extract-answers.json.",
    )
    extract.add_argument(
        "--editor", action="store_true",
        help="Use $EDITOR for multi-line answers (recommended for the pattern body).",
    )

    companyos = sub.add_parser(
        "companyos",
        help="Scaffold a CompanyOS macro layer (the wrapper around per-project builds).",
        description=(
            "Create the 120x macro layer at the given path: clients/, builds/, "
            "patterns/, pipeline/, content/, reference/, daily/, templates/. "
            "This is the wrapper around per-project builds — the 'factory', not the 'house'."
        ),
    )
    companyos.add_argument(
        "path", type=Path,
        help="Directory to scaffold the CompanyOS into (created if missing).",
    )

    journal = sub.add_parser(
        "journal",
        help="Create or open today's planning/journal/YYYY-MM-DD.md entry.",
        description=(
            "Open today's journal entry in $EDITOR. Creates the file with a "
            "short template if it does not yet exist. Use --show to print the "
            "latest entry, --list to list every entry."
        ),
    )
    journal.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(),
        help="Project folder. Default: current working directory.",
    )
    journal.add_argument(
        "--show", action="store_true",
        help="Print the latest journal entry to stdout instead of editing.",
    )
    journal.add_argument(
        "--list", action="store_true", dest="list_all",
        help="List all journal entries, oldest first.",
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
    audit_mode = audit.add_mutually_exclusive_group()
    audit_mode.add_argument(
        "--project", action="store_true",
        help="Force per-project audit (default unless the target looks like a CompanyOS root).",
    )
    audit_mode.add_argument(
        "--companyos", action="store_true",
        help="Force CompanyOS-level audit (orphan builds/clients/patterns, stale proposals).",
    )

    args = parser.parse_args(argv)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "audit":
        return _cmd_audit(args)
    if args.command == "journal":
        return _cmd_journal(args)
    if args.command == "companyos":
        return _cmd_companyos(args)
    if args.command == "extract":
        return _cmd_extract(args)
    if args.command == "onboard":
        return _cmd_onboard(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "patterns":
        return _cmd_patterns(args)
    if args.command == "timeline":
        return _cmd_timeline(args)
    if args.command == "ship":
        return _cmd_ship(args)
    if args.command == "pack":
        return _cmd_pack(args)
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


def _cmd_timeline(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    events = build_timeline(project)
    print(format_timeline(events))
    return 0


def _cmd_ship(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    findings = preflight(project)
    print(format_preflight(findings))
    if any(f.result is CheckResult.FAIL for f in findings):
        return 1
    return 0


def _cmd_pack(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    if args.stdout:
        print(build_pack(project, include_sprint=args.sprint))
        return 0
    target = write_pack(project, include_sprint=args.sprint)
    print(f"Wrote {target}")
    return 0


def _cmd_patterns(args: argparse.Namespace) -> int:
    if args.patterns_command != "review":
        print(f"error: unknown patterns subcommand: {args.patterns_command}",
              file=sys.stderr)
        return 2
    root: Path = args.path.expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    report = review_patterns(root)
    print(format_pattern_report(report))
    return 1 if report.findings else 0


def _cmd_status(args: argparse.Namespace) -> int:
    root: Path = args.path.expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    if not looks_like_companyos(root):
        print(
            f"warning: {root} does not look like a CompanyOS root "
            f"(expected builds/, patterns/, and AGENTS.md). "
            f"Did you mean to run this against the parent of {root.name}?",
            file=sys.stderr,
        )
    rows = companyos_status(root)
    print(format_status(rows))
    # Exit 1 if any project has audit errors — useful in CI.
    any_errors = any(r.audit_errors > 0 for r in rows)
    return 1 if any_errors else 0


def _cmd_onboard(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    if args.stdout:
        print(synthesize_welcome(project))
        return 0
    target = write_welcome(project)
    print(f"Wrote {target}")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    project: Path = args.path.expanduser().resolve()
    if not project.is_dir():
        print(f"error: {project} is not a directory", file=sys.stderr)
        return 2
    if not is_interactive():
        print(
            "error: socrates extract needs a TTY for the interview.",
            file=sys.stderr,
        )
        return 2
    code, _ = run_extract(
        project,
        patterns_dir=args.patterns_dir,
        resume=args.resume,
        editor=args.editor,
    )
    return code


def _cmd_companyos(args: argparse.Namespace) -> int:
    target: Path = args.path.expanduser().resolve()
    try:
        written = scaffold_companyos(target)
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"Scaffolded CompanyOS at: {target}")
    print(f"  Wrote {len(written)} files across {len(set(p.parent for p in written))} folders.")
    print()
    print("Next steps:")
    print(f"  1. cd {target}")
    print("  2. Read AGENTS.md.")
    print("  3. From here, start projects with: socrates init builds/<project-slug>")
    return 0


def _cmd_journal(args: argparse.Namespace) -> int:
    path: Path = args.path.expanduser().resolve()
    if not path.is_dir():
        print(f"error: {path} is not a directory", file=sys.stderr)
        return 2
    return create_or_open_entry(path, show=args.show, list_all=args.list_all)


def _cmd_audit(args: argparse.Namespace) -> int:
    path: Path = args.path.expanduser().resolve()
    if not path.is_dir():
        print(f"error: {path} is not a directory", file=sys.stderr)
        return 2

    # Mode resolution: explicit flag beats auto-detection.
    if args.companyos:
        companyos = True
    elif args.project:
        companyos = False
    else:
        companyos = looks_like_companyos(path)

    report = run_audit(path, companyos=companyos)
    output = format_report(report, as_json=args.json)
    print(output)

    has_errors = any(f.severity is Severity.ERROR for f in report.findings)
    has_warnings = any(f.severity is Severity.WARNING for f in report.findings)
    if has_errors:
        return 1
    if has_warnings and args.strict:
        return 1
    return 0
