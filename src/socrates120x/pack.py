"""The `socrates pack` subcommand — assemble an Architect input bundle.

Every command socrates ships helps the Builder side. The Architect side
(Claude Chat / ChatGPT in a browser) is unaided — operators paste planning
files by hand into a chat thread. `pack` produces the exact paste-able
bundle: one file containing every load-bearing planning document the
Architect needs, in a stable order, separated by clearly-labelled headers.

Output goes to `.socrates-architect-pack.<ext>` in the project root by
default, or to stdout with `--stdout`. The extension follows the chosen
format (md / html / xml).

Optional preambles:

- ``--include-philosophy`` embeds a short, original 120x stance written by
  socrates itself. Safe to include in every pack; never re-uploaded kit
  content. Useful when the Architect chat is fresh (no Project sources set
  up yet) and needs the Architect/Builder split explained inline.

- ``--kit-path PATH`` (or env var ``SOCRATES_KIT_PATH``) also embeds the
  three load-bearing files from a local 120x Operators Kit checkout
  (philosophy, scaffold-instructions, quickstart). Use this when you want
  the FULL kit context in the pack, not just socrates' short summary.

Output format (``--format``):

- ``md`` (default): plain markdown — the historical behavior. Easiest to
  paste into a chat that's expecting markdown.
- ``xml``: section content stays markdown, wrapped in ``<section>`` tags.
  Matches Anthropic's published prompt-engineering recommendation for
  structural delimitation. ~5% token overhead vs. plain markdown.
- ``html``: full HTML, converted from the markdown via the optional
  ``markdown`` library. Install with ``pip install socrates120x[html]``
  or ``pip install markdown``. ~30-50% token overhead vs. markdown.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape as _xml_escape

# Files the kit-path option looks for, in order, in the kit directory.
KIT_FILES: tuple[str, ...] = (
    "120x-architect-builder-philosophy.md",
    "120x-project-scaffold-instructions.md",
    "120x-quickstart.md",
)

PackFormat = Literal["md", "html", "xml"]
SUPPORTED_FORMATS: tuple[PackFormat, ...] = ("md", "html", "xml")
FORMAT_EXTENSIONS: dict[PackFormat, str] = {"md": "md", "html": "html", "xml": "xml"}


@dataclass(frozen=True)
class _Section:
    """One section of the pack — label, file source (if any), body, kind."""
    label: str
    body: str
    # `path` is the on-disk source for traceability; None for synthetic
    # sections (header, footer, philosophy preamble, sprint divider).
    path: str | None = None
    # Discriminator for the XML/HTML renderers so they can pick semantic
    # tags. The MD renderer doesn't use this.
    kind: str = "section"


def build_pack(
    project: Path,
    *,
    include_sprint: str | None = None,
    include_philosophy: bool = False,
    kit_path: Path | None = None,
    format: PackFormat = "md",
) -> str:
    """Return the full Architect input bundle as a single string.

    ``format`` selects the output language:
    - ``md`` (default): plain markdown
    - ``xml``: markdown wrapped in <section> tags
    - ``html``: full HTML (requires the optional `markdown` package)
    """
    if format not in SUPPORTED_FORMATS:
        raise ValueError(
            f"format must be one of {SUPPORTED_FORMATS!r}, got {format!r}"
        )

    sections = _collect_sections(
        project,
        include_sprint=include_sprint,
        include_philosophy=include_philosophy,
        kit_path=kit_path,
    )

    if format == "md":
        return _render_md(sections)
    if format == "xml":
        return _render_xml(project, sections)
    return _render_html(project, sections)


def write_pack(
    project: Path,
    *,
    include_sprint: str | None = None,
    include_philosophy: bool = False,
    kit_path: Path | None = None,
    format: PackFormat = "md",
) -> Path:
    body = build_pack(
        project,
        include_sprint=include_sprint,
        include_philosophy=include_philosophy,
        kit_path=kit_path,
        format=format,
    )
    target = project / f".socrates-architect-pack.{FORMAT_EXTENSIONS[format]}"
    target.write_text(body, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Section collection (format-independent)
# ---------------------------------------------------------------------------


def _collect_sections(
    project: Path,
    *,
    include_sprint: str | None,
    include_philosophy: bool,
    kit_path: Path | None,
) -> list[_Section]:
    out: list[_Section] = [_header_section(project)]

    if include_philosophy:
        out.append(_philosophy_section())

    resolved_kit = _resolve_kit_path(kit_path)
    if resolved_kit is not None:
        out.extend(_kit_sections(resolved_kit))

    for rel, label in (
        ("AGENTS.md", "Project router"),
        ("README.md", "Project README"),
        ("planning/STATE.md", "Current state"),
        ("planning/DOMAIN.md", "Client domain"),
        ("planning/DECISIONS.md", "Decisions"),
        ("planning/RISKS.md", "Risks"),
        ("planning/QUESTIONS.md", "Open questions"),
    ):
        out.append(_file_section(project / rel, rel_display=rel, label=label))

    sprint = _resolve_sprint(project, include_sprint)
    if sprint is not None:
        out.append(_Section(
            label=f"Active sprint: `{sprint.name}`",
            body="",
            kind="sprint-header",
        ))
        sprint_rel = sprint.relative_to(project).as_posix()
        for fname, label in (
            ("requirements.md", "Sprint requirements"),
            ("blueprint.md", "Sprint blueprint"),
            ("acceptance.md", "Sprint acceptance criteria"),
            ("handoff-prompt.md", "Sprint handoff prompt (Builder)"),
        ):
            out.append(_file_section(
                sprint / fname,
                rel_display=f"{sprint_rel}/{fname}",
                label=label,
            ))

    out.append(_footer_section())
    return out


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _header_section(project: Path) -> _Section:
    today = _dt.date.today().isoformat()
    body = f"""_Generated {today} by `socrates pack`. Paste this entire file into your Architect
session (Claude Chat / ChatGPT / etc.) as project context. The Architect should:_

1. _Read every section below in order._
2. _Update its understanding of the domain, decisions, and active sprint._
3. _Answer the operator's questions in a Builder-actionable form
   (planning artifacts, prompts, acceptance criteria — never code)._

_The Builder layer is downstream of this conversation; do not write source code here._"""
    return _Section(
        label=f"Architect input bundle — `{project.name}`",
        body=body,
        kind="header",
    )


def _footer_section() -> _Section:
    body = (
        "_End of bundle. The Architect should now ask the operator what they need next, "
        "treating everything above as the source of truth._"
    )
    return _Section(label="", body=body, kind="footer")


def _philosophy_section() -> _Section:
    """A short, original stance summary written by socrates.

    Loaded from ``socrates120x/templates/architect_preamble.md`` so the text
    can be iterated without editing Python. Deliberately not copied from the
    120x Operators Kit — use ``--kit-path`` if you want the kit's own files
    embedded in the pack.

    The preamble template already begins with a top-level markdown header,
    so the renderers must avoid double-wrapping it.
    """
    text = resources.files("socrates120x").joinpath(
        "templates/architect_preamble.md"
    ).read_text(encoding="utf-8").rstrip()
    return _Section(label="", body=text, kind="preamble-raw")


def _kit_sections(kit: Path) -> list[_Section]:
    out: list[_Section] = []
    for name in KIT_FILES:
        path = kit / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace", encoding="utf-8").strip()
        if not text:
            continue
        out.append(_Section(
            label=f"120x Operators Kit: `{name}`",
            body=text,
            path=name,
            kind="kit",
        ))
    return out


def _file_section(path: Path, *, rel_display: str, label: str) -> _Section:
    if not path.is_file():
        return _Section(
            label=f"{label}  (`{rel_display}`)",
            body="_(file not present — skipped)_",
            path=rel_display,
            kind="missing",
        )
    text = path.read_text(errors="replace", encoding="utf-8").strip()
    if not text:
        return _Section(
            label=f"{label}  (`{rel_display}`)",
            body="_(file is empty)_",
            path=rel_display,
            kind="empty",
        )
    return _Section(
        label=f"{label}  (`{rel_display}`)",
        body=text,
        path=rel_display,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_md(sections: list[_Section]) -> str:
    """Markdown renderer — the historical pack format."""
    parts: list[str] = []
    for s in sections:
        if s.kind == "footer":
            parts.append(f"---\n\n{s.body}")
            continue
        if s.kind == "preamble-raw":
            # Template already has its own top-level header; emit as-is.
            parts.append(s.body)
            continue
        if not s.label:
            parts.append(s.body)
            continue
        if s.body:
            parts.append(f"# {s.label}\n\n{s.body}")
        else:
            parts.append(f"# {s.label}\n")
    return "\n\n".join(filter(None, parts))


def _render_xml(project: Path, sections: list[_Section]) -> str:
    """XML renderer — markdown bodies wrapped in <section> tags.

    Matches Anthropic's published recommendation to use XML-style tags for
    structural delimitation when packing context for Claude. The section
    body remains markdown; only the delimiters are XML. ~5% token overhead.
    """
    today = _dt.date.today().isoformat()
    out: list[str] = [
        f'<bundle generated="{today}" project="{_xml_escape(project.name)}">'
    ]
    for s in sections:
        attrs = f' kind="{_xml_escape(s.kind)}"'
        if s.path:
            attrs += f' path="{_xml_escape(s.path)}"'
        if s.label:
            attrs += f' label="{_xml_escape(s.label)}"'
        # The body contains markdown — escape only the bare minimum so the
        # markdown stays readable. Standard XML chars `<`, `>`, `&` need
        # escaping; markdown's quote/apostrophe usage is irrelevant inside
        # element content.
        body = s.body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if s.kind == "footer":
            out.append(f"  <footer{attrs}>\n{body}\n  </footer>")
        elif s.kind == "header":
            out.append(f"  <header{attrs}>\n{body}\n  </header>")
        else:
            out.append(f"  <section{attrs}>\n{body}\n  </section>")
    out.append("</bundle>")
    return "\n".join(out)


def _render_html(project: Path, sections: list[_Section]) -> str:
    """HTML renderer — markdown converted via the optional `markdown` lib.

    Requires the ``markdown`` package. Install with
    ``pip install socrates120x[html]`` or ``pip install markdown``.
    """
    md = _import_markdown()
    today = _dt.date.today().isoformat()
    rendered_sections: list[str] = []
    for s in sections:
        body_html = md.markdown(
            s.body,
            extensions=["fenced_code", "tables"],
        ) if s.body else ""
        tag = "section"
        if s.kind == "header":
            tag = "header"
        elif s.kind == "footer":
            tag = "footer"
        attrs = f' data-kind="{_xml_escape(s.kind)}"'
        if s.path:
            attrs += f' data-path="{_xml_escape(s.path)}"'
        label_html = ""
        if s.label:
            label_html = f"  <h1>{_xml_escape(s.label)}</h1>\n"
        rendered_sections.append(
            f"<{tag}{attrs}>\n{label_html}  {body_html}\n</{tag}>"
        )
    body = "\n\n".join(rendered_sections)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Architect input bundle — {_xml_escape(project.name)}</title>
<meta name="generated" content="{today}">
<meta name="generator" content="socrates pack">
</head>
<body>
{body}
</body>
</html>"""


def _import_markdown() -> Any:
    try:
        import markdown  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised by error-path test
        raise RuntimeError(
            "--format html requires the `markdown` package. Install with "
            "`pip install socrates120x[html]` or `pip install markdown`."
        ) from exc
    return markdown


# ---------------------------------------------------------------------------
# Resolvers (kit, sprint)
# ---------------------------------------------------------------------------


def _resolve_kit_path(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve() if explicit.exists() else None
    env = os.environ.get("SOCRATES_KIT_PATH")
    if env:
        candidate = Path(env).expanduser().resolve()
        return candidate if candidate.is_dir() else None
    return None


def _resolve_sprint(project: Path, name: str | None) -> Path | None:
    sprints_dir = project / "planning" / "sprints"
    if not sprints_dir.is_dir():
        return None
    if name:
        candidate = sprints_dir / name
        return candidate if candidate.is_dir() else None
    candidates = sorted(p for p in sprints_dir.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None
