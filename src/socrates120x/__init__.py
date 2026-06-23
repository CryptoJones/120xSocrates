"""120xSocrates — Socratic interview tooling for 120x Operators Kit projects.

The package reads in layers:

  support      colors, atomic file I/O, prompting primitives (no 120x knowledge)
  kit          the canonical 120x shapes: scaffold, render, companyos
  interview    the init question set + resumable runner
  audit        consistency checks for projects and CompanyOS roots
  operate      daily rituals: decide, journal, timeline, ship, status
  patterns     the pattern lifecycle: extract + review
  synthesize   derived docs: onboard (WELCOME.md) + pack (Architect bundle)
  cli          argparse wiring for the `socrates` command

This __init__ re-exports the public surface so callers (and the test suite)
can use `from socrates120x import X` without knowing the internal layout.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("socrates120x")
except PackageNotFoundError:
    # Running from a source checkout that was never installed.
    __version__ = "0.0.0+unknown"

from socrates120x.audit import (
    COMPANYOS_CHECKS,
    PROJECT_CHECKS,
    AuditReport,
    Finding,
    Severity,
    check_acceptance_weasels,
    check_adapter_routing,
    check_always_on_risks,
    check_companyos_structure,
    check_orphan_builds,
    check_orphan_pattern_source,
    check_required_files,
    check_scaffold_shape,
    check_sprint_folders,
    check_stale_proposals,
    check_state_freshness,
    check_terminology_used,
    format_report,
    looks_like_companyos,
    run_audit,
)
from socrates120x.cli import _prompt_for_target, _validate_slug, main
from socrates120x.interview import QUESTIONS, Interview
from socrates120x.kit import (
    COMPANYOS_DIRS,
    PROJECT_DIRS,
    PROJECT_FILES,
    render_all,
    scaffold,
    scaffold_companyos,
)
from socrates120x.operate import (
    CheckResult,
    EventKind,
    ProjectStatus,
    ShipFinding,
    TimelineEvent,
    _insert_decision,
    build_timeline,
    companyos_status,
    create_or_open_entry,
    format_preflight,
    format_status,
    format_timeline,
    preflight,
    record_decision,
)
from socrates120x.patterns import (
    PATTERN_QUESTIONS,
    FindingKind,
    PatternFinding,
    PatternReport,
    _resolve_patterns_dir,
    _sanitize_slug,
    format_pattern_report,
    render_pattern,
    review_patterns,
    run_extract,
)
from socrates120x.support import (
    Question,
    ask,
    atomic_write_text,
    editor_command,
    is_interactive,
    locked_read_modify_write,
)
from socrates120x.synthesize import (
    ARCHITECT_PREAMBLE,
    SUPPORTED_FORMATS,
    PackFormat,
    _top_bullets,
    build_pack,
    synthesize_welcome,
    write_pack,
    write_welcome,
)

__all__ = [
    "ARCHITECT_PREAMBLE", "AuditReport", "COMPANYOS_CHECKS", "COMPANYOS_DIRS",
    "CheckResult", "EventKind", "Finding", "FindingKind", "Interview",
    "PATTERN_QUESTIONS", "PROJECT_CHECKS", "PROJECT_DIRS", "PROJECT_FILES",
    "PackFormat", "PatternFinding", "PatternReport", "ProjectStatus",
    "QUESTIONS", "Question", "SUPPORTED_FORMATS", "Severity", "ShipFinding",
    "TimelineEvent", "_resolve_patterns_dir", "_sanitize_slug", "_top_bullets",
    "_prompt_for_target", "_validate_slug", "ask", "atomic_write_text", "build_pack",
    "build_timeline", "check_acceptance_weasels", "check_adapter_routing",
    "check_always_on_risks", "check_companyos_structure", "check_orphan_builds",
    "check_orphan_pattern_source", "check_required_files",
    "check_scaffold_shape", "check_sprint_folders", "check_stale_proposals",
    "check_state_freshness", "check_terminology_used", "companyos_status",
    "_insert_decision", "create_or_open_entry", "editor_command", "format_pattern_report",
    "format_preflight", "format_report", "format_status", "format_timeline",
    "is_interactive", "locked_read_modify_write", "looks_like_companyos",
    "main", "preflight", "record_decision", "render_all", "render_pattern",
    "review_patterns", "run_audit", "run_extract", "scaffold",
    "scaffold_companyos", "synthesize_welcome", "write_pack", "write_welcome",
    "__version__",
]
