"""Tests for socrates pack."""

from __future__ import annotations

from pathlib import Path

import pytest

from socrates120x.pack import (
    SUPPORTED_FORMATS,
    build_pack,
    write_pack,
)
from socrates120x.render import render_all
from socrates120x.scaffold import scaffold


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "demo"
    scaffold(p)
    render_all(p, {
        "project_name": "demo", "client": "AcmeCorp", "tagline": "demo tagline",
        "business_goal": "the goal", "tech_stack": "Python + DuckDB",
        "users": ["op"], "current_process": "manual", "terminology": [],
        "business_rules": [], "decisions": ["choice — reason"], "out_of_scope": [],
        "risks": ["risk one"], "fragile_inputs": "", "open_questions": ["q1?"],
        "sprint1_goal": "", "sprint1_acceptance": ["criterion one"],
        "sprint1_inspect": [], "state_current": "", "state_next": "", "state_blockers": [],
    })
    return p


def test_pack_contains_every_planning_file(project: Path) -> None:
    text = build_pack(project)
    assert "AGENTS.md" in text
    assert "STATE.md" in text
    assert "DOMAIN.md" in text
    assert "DECISIONS.md" in text
    assert "RISKS.md" in text
    assert "QUESTIONS.md" in text
    assert "requirements.md" in text
    assert "blueprint.md" in text
    assert "acceptance.md" in text
    assert "handoff-prompt.md" in text


def test_pack_includes_client_terminology(project: Path) -> None:
    text = build_pack(project)
    assert "AcmeCorp" in text
    assert "choice — reason" in text
    assert "risk one" in text
    assert "q1?" in text


def test_pack_targets_active_sprint(project: Path) -> None:
    text = build_pack(project)
    assert "001-discovery-architecture" in text


def test_pack_specific_sprint(project: Path) -> None:
    # Create a sprint 002 folder with stub files.
    sprint2 = project / "planning" / "sprints" / "002-rebate-engine"
    sprint2.mkdir()
    for fname in ("requirements.md", "blueprint.md", "acceptance.md", "handoff-prompt.md"):
        (sprint2 / fname).write_text(f"# {fname} (sprint 2)")
    text = build_pack(project, include_sprint="002-rebate-engine")
    assert "002-rebate-engine" in text
    # Sprint 1 files should NOT appear since we asked for sprint 2.
    assert "001-discovery-architecture" not in text


def test_pack_handles_missing_file_gracefully(project: Path) -> None:
    (project / "planning" / "STATE.md").unlink()
    text = build_pack(project)
    assert "file not present — skipped" in text


def test_write_pack_creates_file(project: Path) -> None:
    target = write_pack(project)
    assert target == project / ".socrates-architect-pack.md"
    assert target.is_file()
    assert "AcmeCorp" in target.read_text()


def test_pack_starts_with_architect_header(project: Path) -> None:
    text = build_pack(project)
    assert text.startswith("# Architect input bundle")
    assert "Paste this entire file" in text


def test_pack_include_philosophy_embeds_socrates_preamble(project: Path) -> None:
    text = build_pack(project, include_philosophy=True)
    assert "120x Architect / Builder stance" in text
    # Should NOT contain kit-file section headers unless --kit-path was passed.
    assert "# 120x Operators Kit:" not in text


def test_pack_default_omits_philosophy(project: Path) -> None:
    text = build_pack(project)
    assert "120x Architect / Builder stance" not in text


def test_pack_kit_path_embeds_kit_files(project: Path, tmp_path: Path) -> None:
    kit = tmp_path / "fake-kit"
    kit.mkdir()
    (kit / "120x-architect-builder-philosophy.md").write_text(
        "# Fake philosophy doc body content."
    )
    (kit / "120x-project-scaffold-instructions.md").write_text(
        "# Fake scaffold instructions content."
    )
    # Quickstart deliberately absent — pack should skip cleanly.
    text = build_pack(project, kit_path=kit)
    assert "120x-architect-builder-philosophy.md" in text
    assert "Fake philosophy doc body" in text
    assert "120x-project-scaffold-instructions.md" in text
    assert "120x-quickstart.md" not in text


def test_pack_kit_path_via_env_var(project: Path, tmp_path: Path, monkeypatch) -> None:
    kit = tmp_path / "env-kit"
    kit.mkdir()
    (kit / "120x-quickstart.md").write_text("# Quickstart from env\n")
    monkeypatch.setenv("SOCRATES_KIT_PATH", str(kit))
    text = build_pack(project)
    assert "Quickstart from env" in text


def test_pack_kit_path_missing_dir_skipped(project: Path) -> None:
    # Non-existent path should be silently skipped (no crash).
    text = build_pack(project, kit_path=Path("/tmp/does-not-exist-socrates"))
    # No kit section header should appear.
    assert "# 120x Operators Kit:" not in text


def test_pack_philosophy_and_kit_can_combine(project: Path, tmp_path: Path) -> None:
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "120x-architect-builder-philosophy.md").write_text("# Kit philosophy.\n")
    text = build_pack(project, include_philosophy=True, kit_path=kit)
    assert "120x Architect / Builder stance" in text  # socrates preamble
    assert "Kit philosophy" in text  # kit file


# ---------------------------------------------------------------------------
# --format md|html|xml
# ---------------------------------------------------------------------------


def test_supported_formats_constant() -> None:
    # Guard against accidental drift between the constant and the CLI choices.
    assert SUPPORTED_FORMATS == ("md", "html", "xml")


def test_pack_rejects_unknown_format(project: Path) -> None:
    with pytest.raises(ValueError, match="format must be one of"):
        build_pack(project, format="json")  # type: ignore[arg-type]


def test_pack_md_format_is_default(project: Path) -> None:
    # The unparameterized call (existing behavior) and an explicit md call
    # produce identical output.
    assert build_pack(project) == build_pack(project, format="md")


def test_pack_md_format_has_markdown_headers(project: Path) -> None:
    text = build_pack(project, format="md")
    # Markdown headers, not HTML/XML tags.
    assert text.startswith("# Architect input bundle")
    assert "<section" not in text
    assert "<!doctype" not in text


def test_pack_xml_format_wraps_sections_in_tags(project: Path) -> None:
    text = build_pack(project, format="xml")
    # Bundle wrapper + at least one section + header + footer.
    assert text.startswith("<bundle ")
    assert text.rstrip().endswith("</bundle>")
    assert "<header " in text
    assert "<section " in text
    assert "<footer " in text
    # Source content (markdown bodies stay markdown inside the tags) should
    # still flow through.
    assert "AcmeCorp" in text


def test_pack_xml_format_includes_path_and_label_attrs(project: Path) -> None:
    text = build_pack(project, format="xml")
    # The DECISIONS file should appear as a section with path + label attrs.
    assert 'path="planning/DECISIONS.md"' in text
    assert 'label="Decisions' in text


def test_pack_xml_format_escapes_xml_specials(tmp_path: Path) -> None:
    # Build a minimal project whose content contains XML-special chars.
    p = tmp_path / "xml-escape-demo"
    scaffold(p)
    (p / "planning" / "DECISIONS.md").write_text(
        "# Decisions\n\n- chose <X> over Y & Z for the foo>bar case\n"
    )
    text = build_pack(p, format="xml")
    # The body is inside an XML element — `<`, `>`, `&` must be escaped.
    assert "&lt;X&gt;" in text
    assert "Y &amp; Z" in text
    # Raw unescaped angle brackets from the content should NOT appear inside
    # the element body. (We allow them in our own emitted tags, naturally.)
    assert "<X>" not in text


def test_pack_html_format_emits_doctype_and_html_tags(project: Path) -> None:
    text = build_pack(project, format="html")
    assert text.startswith("<!doctype html>")
    assert "<html lang=\"en\">" in text
    assert "<head>" in text
    assert "<body>" in text
    assert text.rstrip().endswith("</html>")
    # Markdown should have been converted — headers become <h1>/<h2>/etc.
    # The label of the AGENTS section appears as an <h1> inside its section.
    assert "<h1>" in text


def test_pack_html_format_includes_section_kind_attr(project: Path) -> None:
    text = build_pack(project, format="html")
    # Header section gets a <header> tag with data-kind="header".
    assert "<header data-kind=\"header\"" in text
    # Regular file sections get <section data-kind="section">.
    assert "<section data-kind=\"section\"" in text
    assert "<footer data-kind=\"footer\"" in text


def test_write_pack_picks_correct_extension(project: Path) -> None:
    md_target = write_pack(project, format="md")
    assert md_target.suffix == ".md"
    assert md_target.name == ".socrates-architect-pack.md"

    xml_target = write_pack(project, format="xml")
    assert xml_target.suffix == ".xml"
    assert xml_target.name == ".socrates-architect-pack.xml"

    html_target = write_pack(project, format="html")
    assert html_target.suffix == ".html"
    assert html_target.name == ".socrates-architect-pack.html"


def test_pack_all_formats_carry_user_content_through(project: Path) -> None:
    # Independent of format, the operator's planning content must reach the
    # output. AcmeCorp comes from the fixture's render_all answers.
    for fmt in SUPPORTED_FORMATS:
        text = build_pack(project, format=fmt)
        assert "AcmeCorp" in text, f"format={fmt} dropped user content"
        assert "choice" in text and "reason" in text, f"format={fmt} dropped a decision"


def test_pack_html_format_error_when_markdown_missing(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate the markdown package not being installed by making the
    # internal import helper raise. This avoids actually uninstalling the
    # dev-dep used by other tests.
    import socrates120x.pack as pack_module

    def _raise() -> None:
        raise RuntimeError(
            "--format html requires the `markdown` package. Install with "
            "`pip install socrates120x[html]` or `pip install markdown`."
        )

    monkeypatch.setattr(pack_module, "_import_markdown", _raise)
    with pytest.raises(RuntimeError, match="requires the `markdown` package"):
        build_pack(project, format="html")
