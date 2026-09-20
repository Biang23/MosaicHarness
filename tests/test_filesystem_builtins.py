from __future__ import annotations

from pathlib import Path

import pytest

from mosaic_harness import (
    BuiltinsConfig,
    DocumentsConfig,
    FilesystemConfig,
    MosaicConfig,
    MosaicHarness,
    ToolsConfig,
)


def filesystem_harness(root: Path) -> MosaicHarness:
    return MosaicHarness(
        config=MosaicConfig(
            enabled_capabilities=("tools",),
            tools=ToolsConfig(enabled=True),
            builtins=BuiltinsConfig(tools_enabled=True, skills_enabled=False),
            filesystem=FilesystemConfig(enabled=True, roots=(str(root),)),
        )
    )


def document_harness(root: Path) -> MosaicHarness:
    return MosaicHarness(
        config=MosaicConfig(
            enabled_capabilities=("tools",),
            tools=ToolsConfig(enabled=True),
            builtins=BuiltinsConfig(tools_enabled=True, skills_enabled=False),
            filesystem=FilesystemConfig(enabled=True, roots=(str(root),)),
            documents=DocumentsConfig(enabled=True, max_pages=2, max_output_chars=20),
        )
    )


def test_filesystem_tools_are_disabled_by_default() -> None:
    assert "read_file" not in MosaicHarness().tools.names
    assert "list_files" not in MosaicHarness().tools.names


def test_read_file_and_list_files_are_root_scoped(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello mosaic", encoding="utf-8")
    sdk = filesystem_harness(tmp_path)

    read_result = sdk.tools.resolve(("read_file",))[0].invoke({"path": "notes.txt"})
    list_result = sdk.tools.resolve(("list_files",))[0].invoke({"path": "."})

    assert read_result.data["text"] == "hello mosaic"
    assert "notes.txt" in list_result.data["files"]


def test_read_file_rejects_path_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    sdk = filesystem_harness(tmp_path)

    result = sdk.tools.resolve(("read_file",))[0].invoke({"path": "../outside-secret.txt"})

    assert result.status == "error"
    assert "outside" in result.summary.lower() or "allowed" in result.summary.lower()


def test_extract_csv_schema_returns_bounded_structured_summary(tmp_path: Path) -> None:
    (tmp_path / "users.csv").write_text(
        "name,age,active\nAlice,30,true\nBob,41,false\n",
        encoding="utf-8",
    )
    sdk = filesystem_harness(tmp_path)

    result = sdk.tools.resolve(("extract_csv_schema",))[0].invoke(
        {"path": "users.csv", "sample_rows": 1}
    )

    assert result.status == "success"
    assert result.data["columns"] == ["name", "age", "active"]
    assert result.data["row_count"] == 2
    assert len(result.data["sample_rows"]) == 1


def test_search_document_is_root_scoped_and_bounded(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Mosaic search target\nother line", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.md").write_text("mosaic second target", encoding="utf-8")
    sdk = filesystem_harness(tmp_path)

    result = sdk.tools.resolve(("search_document",))[0].invoke(
        {"query": "mosaic", "max_results": 1}
    )

    assert result.status == "success"
    assert len(result.data["matches"]) == 1
    assert result.data["matches"][0]["path"] == "a.txt"


def test_document_tools_are_disabled_by_default() -> None:
    assert "extract_pdf_text" not in MosaicHarness().tools.names
    assert "extract_docx_text" not in MosaicHarness().tools.names


def test_extract_docx_text_is_bounded_and_root_scoped(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Mosaic document text that is deliberately long")
    document.save(tmp_path / "notes.docx")
    sdk = document_harness(tmp_path)

    result = sdk.tools.resolve(("extract_docx_text",))[0].invoke({"path": "notes.docx"})

    assert result.status == "success"
    assert result.data["text"].startswith("Mosaic document")
    assert len(result.data["text"]) == 20


def test_extract_pdf_text_reports_pages(tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with (tmp_path / "blank.pdf").open("wb") as handle:
        writer.write(handle)
    sdk = document_harness(tmp_path)

    result = sdk.tools.resolve(("extract_pdf_text",))[0].invoke({"path": "blank.pdf"})

    assert result.status == "success"
    assert result.data["pages"] == 1
    assert result.data["text"] == ""


def test_document_tools_require_filesystem_category() -> None:
    config = MosaicConfig(
        enabled_capabilities=("tools",),
        tools=ToolsConfig(enabled=True),
        builtins=BuiltinsConfig(tools_enabled=True, skills_enabled=False),
        documents=DocumentsConfig(enabled=True),
    )

    assert "extract_pdf_text" not in MosaicHarness(config=config).tools.names
