"""The Socratic interview — the canonical init question set and runner.

The prompting primitives moved to `prompting.py`; this module owns:

- `QUESTIONS`: the 18 questions used by `socrates init`.
- `Interview`: the resumable runner that loops over a question set, saves
  answers incrementally, and calls into `prompting` for I/O.

Reusing this class with a different `questions` tuple drives `extract`.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from socrates120x.prompting import (
    InputFn,
    OutputFn,
    Question,
    ask,
    confirm_change,
    is_interactive,
    print_section_banner,
    show_existing,
)

__all__ = ["Interview", "Question", "QUESTIONS", "is_interactive"]


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* via a same-directory tempfile + rename.

    A naked path.write_text() opens, truncates, and writes — if the process
    is killed mid-write (Ctrl-C, OOM, power loss) the file is left
    truncated or partially written, which then breaks the next
    `socrates init --resume` with a JSONDecodeError stacktrace.
    Tempfile + rename is atomic on POSIX (and on Windows since Python 3.3
    via os.replace) so the file on disk is either the old contents or
    the new contents — never half-and-half.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        # os.replace is atomic across filesystems on the same device; if the
        # tempfile lives in the same dir as the target (which it does here),
        # we're always on the same device.
        os.replace(tmp, path)
    finally:
        # If anything went wrong, leave a clean directory — don't strand the
        # tempfile for the next run to wonder about.
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


# The full init interview. Order matters — earlier answers prime the user for
# later ones (decisions before risks, risks before open questions, etc.).
QUESTIONS: tuple[Question, ...] = (
    # --- Project identity -------------------------------------------------
    Question(
        key="client",
        prompt="Who is the client?",
        section="Identity",
        help="Company or team name. 'Internal' is a fine answer.",
        required=True,
    ),
    Question(
        key="tagline",
        prompt="One-sentence tagline — what is this thing?",
        section="Identity",
        help="The kind of sentence you'd put under the project name in a README.",
        required=True,
    ),
    Question(
        key="business_goal",
        prompt="What is the business goal? Why is this worth building?",
        section="Identity",
        type="multiline",
        help="A paragraph. The motivating outcome, not the feature list.",
        required=True,
    ),
    Question(
        key="tech_stack",
        prompt="Tech stack (best guess — 'TBD' is OK).",
        section="Identity",
        help='Example: "Python + Supabase + Streamlit". Leave as TBD if Sprint 001 is supposed to decide.',
        default="TBD",
    ),
    # --- Domain -----------------------------------------------------------
    Question(
        key="users",
        prompt="Who uses this? List each user role on its own line.",
        section="Domain",
        type="list",
        help='One role per line. Example:\n  - Operations manager (daily)\n  - Sales lead (weekly review)',
    ),
    Question(
        key="current_process",
        prompt="What does the current (manual) process look like?",
        section="Domain",
        type="multiline",
        help="What happens today — spreadsheets, emails, copy/paste between systems, etc. The thing this project is replacing or augmenting.",
    ),
    Question(
        key="terminology",
        prompt="Client-specific terminology — list terms with definitions (one per line, format: 'term — definition').",
        section="Domain",
        type="list",
        help='Examples:\n  - rebate cycle — quarterly window when payouts are calculated\n  - tier A vendor — pre-approved supplier with auto-pay enabled',
    ),
    Question(
        key="business_rules",
        prompt="Core business rules / invariants (one per line).",
        section="Domain",
        type="list",
        help='Hard truths the system must respect. Example:\n  - Money is stored in integer cents, never floats\n  - A rebate below $5 is never paid out',
    ),
    # --- Decisions --------------------------------------------------------
    Question(
        key="decisions",
        prompt="Decisions already made (one per line, format: 'decision — because').",
        section="Decisions",
        type="list",
        help='Each line: the choice plus the reason. Example:\n  - Supabase over self-hosted Postgres — client already has an account\n  - Ingest via file drop, not API — vendors will not expose an API',
    ),
    Question(
        key="out_of_scope",
        prompt="Explicitly OUT of scope (one per line).",
        section="Decisions",
        type="list",
        help='Things you might be tempted to build but will not. Example:\n  - Mobile app (web only)\n  - Multi-tenant — single-client deployment only',
    ),
    # --- Risks ------------------------------------------------------------
    Question(
        key="risks",
        prompt="Known risks / traps (one per line).",
        section="Risks",
        type="list",
        help='What could derail this? Example:\n  - Source spreadsheets may change column order between quarters\n  - Historical data has inconsistent units (some rows in lbs, some in kg)',
    ),
    Question(
        key="fragile_inputs",
        prompt="Anything fragile about the inputs / data sources?",
        section="Risks",
        type="multiline",
        help="Format drift, missing values, multiple sources of truth, manual upstream steps. A short paragraph is fine.",
    ),
    # --- Open questions ---------------------------------------------------
    Question(
        key="open_questions",
        prompt="What do you still NOT know? (one question per line)",
        section="Questions",
        type="list",
        help='Honest gaps. The Architect will pick these up. Example:\n  - Who owns rebate disputes once flagged?\n  - Is there a maximum rebate per vendor per cycle?',
    ),
    # --- Sprint 001 -------------------------------------------------------
    Question(
        key="sprint1_goal",
        prompt="Sprint 001 (Discovery & Architecture) — what is the goal of THIS sprint?",
        section="Sprint 001",
        type="multiline",
        help="Default for Sprint 001 is producing the planning artifacts and a Sprint 002 build plan. If you have a more specific goal, say so.",
        default="Produce a Builder-ready architecture: confirmed scope, file-level blueprint, and acceptance criteria for Sprint 002.",
    ),
    Question(
        key="sprint1_acceptance",
        prompt="Sprint 001 acceptance criteria (one per line — what must be true to ship this sprint?).",
        section="Sprint 001",
        type="list",
        help='Each criterion should be objectively checkable. Example:\n  - DOMAIN.md describes the rebate cycle in client terminology\n  - blueprint.md lists every file Sprint 002 will create\n  - At least one sample input file is committed to samples/',
    ),
    Question(
        key="sprint1_inspect",
        prompt="Files / sources the Builder should inspect first (one per line — optional).",
        section="Sprint 001",
        type="list",
        help='Example:\n  - samples/rebate-q3.xlsx\n  - references/client-pricing-deck.pdf',
    ),
    # --- State ------------------------------------------------------------
    Question(
        key="state_current",
        prompt="What is the current status, in one or two lines?",
        section="State",
        type="multiline",
        default="Sprint 001 (Discovery & Architecture) — interview complete, planning files populated. Awaiting Architect review.",
    ),
    Question(
        key="state_next",
        prompt="What is the very next action?",
        section="State",
        default="Review planning/ files with the Architect; resolve QUESTIONS.md; produce Sprint 002 requirements.",
    ),
    Question(
        key="state_blockers",
        prompt="Current blockers (one per line, or leave empty).",
        section="State",
        type="list",
    ),
)


@dataclass
class Interview:
    """Stateful interview against an on-disk answer file.

    `project_name` is optional. Callers that want the answer dict to carry a
    `project_name` key (init flow) should pass it; callers that do not
    (extract flow) should leave it empty.
    """

    answers_path: Path
    project_name: str = ""
    answers: dict[str, Any] = field(default_factory=dict)
    resume: bool = False
    editor: bool = False
    questions: tuple[Question, ...] = field(default_factory=lambda: QUESTIONS)

    def load(self) -> None:
        """Load answers from disk if --resume was passed.

        A previous run that was killed mid-save could have left a corrupted
        file. Instead of blowing up with a JSONDecodeError stacktrace, warn
        the operator and start fresh — they'd have to re-answer questions
        either way, and the alternative is unrecoverable from the CLI.
        """
        if not (self.answers_path.exists() and self.resume):
            return
        try:
            self.answers = json.loads(self.answers_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"warning: could not read {self.answers_path}: {e}\n"
                f"  Starting interview from scratch. The corrupt file will be "
                f"overwritten on the first answer.",
                file=sys.stderr,
            )
            self.answers = {}

    def save(self) -> None:
        # Atomic write — see _atomic_write_text. Without this, Ctrl-C during
        # save() leaves a truncated file that crashes the next --resume.
        _atomic_write_text(
            self.answers_path,
            json.dumps(self.answers, indent=2) + "\n",
        )

    def run(
        self,
        *,
        input_fn: InputFn = input,
        output_fn: OutputFn = print,
    ) -> None:
        self.load()
        if self.project_name:
            self.answers.setdefault("project_name", self.project_name)
        total = len(self.questions)
        current_section: str | None = None
        for i, q in enumerate(self.questions, start=1):
            if q.section != current_section:
                print_section_banner(q.section, output_fn)
                current_section = q.section

            existing = self.answers.get(q.key)
            if self.resume and existing not in (None, "", []):
                output_fn(f"[{i}/{total}] {q.prompt}")
                show_existing(existing, output_fn)
                if not confirm_change(input_fn, output_fn):
                    continue

            value = ask(q, i, total, input_fn, output_fn, editor=self.editor)
            self.answers[q.key] = value
            self.save()

        output_fn("")
        output_fn("Interview complete. Saved to: " + str(self.answers_path))
