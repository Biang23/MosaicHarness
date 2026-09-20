from __future__ import annotations

import csv
import io
from importlib import import_module
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from ..tools.result import ToolResult
from .base import MosaicTool


class FilePathArgs(BaseModel):
    path: str = Field(default=".", min_length=1, max_length=4_000)


class ReadFileArgs(FilePathArgs):
    max_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)


class ListFilesArgs(FilePathArgs):
    recursive: bool = False
    max_entries: int = Field(default=200, ge=1, le=2_000)


class CsvSchemaArgs(FilePathArgs):
    sample_rows: int = Field(default=5, ge=0, le=100)
    max_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)


class SearchDocumentArgs(BaseModel):
    query: str = Field(min_length=1, max_length=1_000)
    path: str = Field(default=".", min_length=1, max_length=4_000)
    max_results: int = Field(default=20, ge=1, le=200)
    max_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)


class DocumentArgs(FilePathArgs):
    max_pages: int = Field(default=50, ge=1, le=500)
    max_output_chars: int = Field(default=200_000, ge=1, le=2_000_000)


class _FilesystemTool(MosaicTool):
    category = "filesystem"
    risk_level = "medium"
    required_categories = ("filesystem",)
    _roots: tuple[Path, ...] = PrivateAttr()

    def __init__(self, *, roots: tuple[str, ...], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._roots = tuple(Path(root).expanduser().resolve() for root in roots)

    def _resolve(self, path: str) -> Path:
        if not self._roots:
            raise ValueError("no filesystem roots are configured")
        requested = Path(path).expanduser()
        for root in self._roots:
            candidate = (requested if requested.is_absolute() else root / requested).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            return candidate
        raise ValueError("path is outside configured filesystem roots")


class ReadFileTool(_FilesystemTool):
    name: str = "read_file"
    description: str = "Read a UTF-8 text file inside configured filesystem roots."

    def __init__(self, *, roots: tuple[str, ...]) -> None:
        super().__init__(roots=roots, args_schema=ReadFileArgs)

    def _run(self, path: str = ".", max_bytes: int = 1_000_000, **kwargs: object) -> ToolResult:
        del kwargs
        try:
            file_path = self._resolve(path)
            if not file_path.is_file():
                raise ValueError("path is not a regular file")
            data = file_path.read_bytes()
            if len(data) > max_bytes:
                raise ValueError("file exceeds max_bytes")
            text = data.decode("utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            summary = _filesystem_error_summary(exc)
            return ToolResult.error(
                summary,
                next_actions=("check_path_and_permissions", "reduce_requested_file_size"),
            )
        return ToolResult.success(
            f"Read {file_path.name}",
            data={"path": str(file_path), "text": text},
        )


class ListFilesTool(_FilesystemTool):
    name: str = "list_files"
    description: str = "List files inside configured filesystem roots."

    def __init__(self, *, roots: tuple[str, ...]) -> None:
        super().__init__(roots=roots, args_schema=ListFilesArgs)

    def _run(
        self,
        path: str = ".",
        recursive: bool = False,
        max_entries: int = 200,
        **kwargs: object,
    ) -> ToolResult:
        del kwargs
        try:
            directory = self._resolve(path)
            if not directory.is_dir():
                raise ValueError("path is not a directory")
            entries = directory.rglob("*") if recursive else directory.iterdir()
            files = sorted(str(item.relative_to(directory)) for item in entries if item.is_file())[
                :max_entries
            ]
        except (OSError, ValueError) as exc:
            summary = _filesystem_error_summary(exc)
            return ToolResult.error(
                summary,
                next_actions=("check_path_and_permissions",),
            )
        return ToolResult.success(
            f"Listed {len(files)} files",
            data={"path": str(directory), "files": files},
        )


class ExtractCsvSchemaTool(_FilesystemTool):
    name: str = "extract_csv_schema"
    description: str = "Extract CSV columns, row count, inferred types, and sample rows."

    def __init__(self, *, roots: tuple[str, ...]) -> None:
        super().__init__(roots=roots, args_schema=CsvSchemaArgs)

    def _run(
        self,
        path: str,
        sample_rows: int = 5,
        max_bytes: int = 1_000_000,
        **kwargs: object,
    ) -> ToolResult:
        del kwargs
        try:
            file_path = self._resolve(path)
            if not file_path.is_file():
                raise ValueError("path is not a regular file")
            data = file_path.read_bytes()
            if len(data) > max_bytes:
                raise ValueError("file exceeds max_bytes")
            rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
            columns = list(rows[0]) if rows else []
            sample = rows[:sample_rows]
            inferred_types = {
                column: _infer_csv_type([row.get(column, "") for row in rows]) for column in columns
            }
        except (OSError, UnicodeError, ValueError, csv.Error) as exc:
            return ToolResult.error(
                f"CSV extraction failed: {type(exc).__name__}",
                next_actions=("check_csv_format_and_path",),
            )
        return ToolResult.success(
            f"Extracted CSV schema from {file_path.name}",
            data={
                "path": str(file_path),
                "columns": columns,
                "inferred_types": inferred_types,
                "row_count": len(rows),
                "sample_rows": sample,
            },
        )


class SearchDocumentTool(_FilesystemTool):
    name: str = "search_document"
    description: str = "Search bounded text files inside configured filesystem roots."

    def __init__(self, *, roots: tuple[str, ...]) -> None:
        super().__init__(roots=roots, args_schema=SearchDocumentArgs)

    def _run(
        self,
        query: str,
        path: str = ".",
        max_results: int = 20,
        max_bytes: int = 1_000_000,
        **kwargs: object,
    ) -> ToolResult:
        del kwargs
        try:
            directory = self._resolve(path)
            if not directory.is_dir():
                raise ValueError("path is not a directory")
            matches: list[dict[str, object]] = []
            candidates = sorted(item for item in directory.rglob("*") if item.is_file())
            for file_path in candidates:
                if len(matches) >= max_results:
                    break
                try:
                    data = file_path.read_bytes()
                    if len(data) > max_bytes:
                        continue
                    text = data.decode("utf-8")
                except (OSError, UnicodeError):
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if query.casefold() not in line.casefold():
                        continue
                    matches.append(
                        {
                            "path": str(file_path.relative_to(directory)),
                            "line": line_number,
                            "text": line[:2_000],
                        }
                    )
                    if len(matches) >= max_results:
                        break
        except (OSError, ValueError) as exc:
            return ToolResult.error(
                _filesystem_error_summary(exc),
                next_actions=("check_path_and_permissions",),
            )
        return ToolResult.success(
            f"Found {len(matches)} document matches",
            data={"query": query, "path": str(directory), "matches": matches},
        )


class ExtractPdfTextTool(_FilesystemTool):
    name: str = "extract_pdf_text"
    description: str = "Extract bounded text from a PDF inside configured roots."
    _default_max_pages: int = PrivateAttr()
    _default_max_output_chars: int = PrivateAttr()

    def __init__(
        self,
        *,
        roots: tuple[str, ...],
        max_pages: int = 50,
        max_output_chars: int = 200_000,
    ) -> None:
        super().__init__(roots=roots, args_schema=DocumentArgs)
        self._default_max_pages = max_pages
        self._default_max_output_chars = max_output_chars

    def _run(
        self,
        path: str,
        max_pages: int | None = None,
        max_output_chars: int = 200_000,
        **kwargs: object,
    ) -> ToolResult:
        del kwargs
        try:
            pypdf = import_module("pypdf")

            file_path = self._resolve(path)
            reader = pypdf.PdfReader(str(file_path))
            page_limit = min(
                max_pages or self._default_max_pages,
                self._default_max_pages,
                len(reader.pages),
            )
            text = "\n\n".join(
                (reader.pages[index].extract_text() or "") for index in range(page_limit)
            )
            text = text[: min(max_output_chars, self._default_max_output_chars)]
        except ImportError:
            return ToolResult.error(
                "PDF support is not installed.",
                next_actions=("install_mosaic_documents_extra",),
            )
        except (OSError, ValueError) as exc:
            return ToolResult.error(
                f"PDF extraction failed: {type(exc).__name__}",
                next_actions=("check_path_and_pdf_format",),
            )
        return ToolResult.success(
            f"Extracted text from {file_path.name}",
            data={"path": str(file_path), "pages": page_limit, "text": text},
        )


class ExtractDocxTextTool(_FilesystemTool):
    name: str = "extract_docx_text"
    description: str = "Extract bounded text from a DOCX inside configured roots."
    _default_max_output_chars: int = PrivateAttr()

    def __init__(self, *, roots: tuple[str, ...], max_output_chars: int = 200_000) -> None:
        super().__init__(roots=roots, args_schema=DocumentArgs)
        self._default_max_output_chars = max_output_chars

    def _run(
        self,
        path: str,
        max_pages: int = 50,
        max_output_chars: int | None = None,
        **kwargs: object,
    ) -> ToolResult:
        del max_pages, kwargs
        try:
            docx = import_module("docx")

            file_path = self._resolve(path)
            document = docx.Document(str(file_path))
            paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
            output_limit = min(
                max_output_chars or self._default_max_output_chars,
                self._default_max_output_chars,
            )
            text = "\n".join(paragraphs)[:output_limit]
        except ImportError:
            return ToolResult.error(
                "DOCX support is not installed.",
                next_actions=("install_mosaic_documents_extra",),
            )
        except (OSError, ValueError) as exc:
            return ToolResult.error(
                f"DOCX extraction failed: {type(exc).__name__}",
                next_actions=("check_path_and_docx_format",),
            )
        return ToolResult.success(
            f"Extracted text from {file_path.name}",
            data={"path": str(file_path), "text": text},
        )


def filesystem_tools(roots: tuple[str, ...]) -> tuple[MosaicTool, ...]:
    return (
        ListFilesTool(roots=roots),
        ReadFileTool(roots=roots),
        ExtractCsvSchemaTool(roots=roots),
        SearchDocumentTool(roots=roots),
    )


def document_tools(
    roots: tuple[str, ...],
    *,
    max_pages: int,
    max_output_chars: int,
) -> tuple[MosaicTool, ...]:
    return (
        ExtractPdfTextTool(
            roots=roots,
            max_pages=max_pages,
            max_output_chars=max_output_chars,
        ),
        ExtractDocxTextTool(roots=roots, max_output_chars=max_output_chars),
    )


def _filesystem_error_summary(exc: Exception) -> str:
    if isinstance(exc, ValueError) and "outside" in str(exc):
        return "Filesystem path is outside configured roots."
    if isinstance(exc, ValueError) and "max_bytes" in str(exc):
        return "File exceeds the configured maximum size."
    return f"Filesystem operation failed: {type(exc).__name__}"


def _infer_csv_type(values: list[str]) -> str:
    non_empty = [value.strip() for value in values if value.strip()]
    if not non_empty:
        return "empty"
    if all(value.lower() in {"true", "false"} for value in non_empty):
        return "boolean"
    try:
        for value in non_empty:
            float(value)
        return "number"
    except ValueError:
        return "string"
