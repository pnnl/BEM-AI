"""Bounded, page-preserving PDF text extraction."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from automa_ai.tools.base import BaseDefaultTool
from automa_ai.tools.pdf_reader.config import PdfReaderToolConfig


class PdfReaderInput(BaseModel):
    """A local upload path or an approved ``s3://bucket/key`` source."""

    source: str = Field(min_length=1)
    page_numbers: list[int] | None = None


class PdfReaderTool(BaseDefaultTool):
    type = "pdf_reader"

    def __init__(self, config: PdfReaderToolConfig):
        self.config = config

    @property
    def args_schema(self) -> type[BaseModel]:
        return PdfReaderInput

    @property
    def description(self) -> str:
        return (
            "Extract raw text from each requested page of a local uploaded PDF or "
            "an approved S3 PDF. Returns page numbers and text without summarizing, "
            "formatting, OCR, or layout reconstruction."
        )

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        args = PdfReaderInput.model_validate(payload)
        temporary_path: Path | None = None
        try:
            source_path, normalized_source, temporary_path = self._resolve_source(
                args.source
            )
            return self._extract(source_path, normalized_source, args.page_numbers)
        except (BotoCoreError, ClientError, OSError, PdfReadError, ValueError) as exc:
            return _failure(args.source, str(exc))
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _resolve_source(self, source: str) -> tuple[Path, str, Path | None]:
        parsed = urlparse(source)
        if parsed.scheme == "s3":
            return self._download_s3(source, parsed)
        if parsed.scheme:
            raise ValueError("Only local paths and s3:// URIs are supported.")

        path = Path(source).expanduser().resolve()
        upload_root = Path(self.config.upload_root)
        if not path.is_relative_to(upload_root):
            raise ValueError("Local PDF source must be inside upload_root.")
        if path.suffix.lower() != ".pdf":
            raise ValueError("Source must have a .pdf extension.")
        if not path.is_file():
            raise ValueError("Local PDF source does not exist or is not a file.")
        if path.stat().st_size > self.config.max_file_bytes:
            raise ValueError("PDF exceeds configured max_file_bytes.")
        return path, str(path), None

    def _download_s3(self, source: str, parsed: Any) -> tuple[Path, str, Path]:
        s3_config = self.config.s3
        bucket, key = parsed.netloc, parsed.path.lstrip("/")
        if not s3_config.enabled:
            raise ValueError("S3 PDF sources are disabled.")
        if not bucket or not key:
            raise ValueError("S3 source must include a bucket and object key.")
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError(
                "S3 source must not include parameters, a query, or a fragment."
            )
        if bucket not in s3_config.allowed_buckets:
            raise ValueError("S3 bucket is not allowed.")
        if s3_config.allowed_key_prefixes and not any(
            key.startswith(prefix) for prefix in s3_config.allowed_key_prefixes
        ):
            raise ValueError("S3 object key is not allowed.")
        if not key.lower().endswith(".pdf"):
            raise ValueError("Source must have a .pdf extension.")

        client = boto3.client("s3", region_name=s3_config.region_name)
        metadata = client.head_object(Bucket=bucket, Key=key)
        size = metadata.get("ContentLength")
        if not isinstance(size, int) or size < 0:
            raise ValueError("S3 object did not report a valid content length.")
        if size > self.config.max_file_bytes:
            raise ValueError("PDF exceeds configured max_file_bytes.")

        descriptor, temp_name = tempfile.mkstemp(suffix=".pdf")
        os.close(descriptor)
        temp_path = Path(temp_name)
        try:
            with temp_path.open("wb") as file_object:
                client.download_fileobj(bucket, key, file_object)
            if temp_path.stat().st_size > self.config.max_file_bytes:
                raise ValueError("Downloaded PDF exceeds configured max_file_bytes.")
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path, source, temp_path

    def _extract(
        self, path: Path, source: str, requested_pages: list[int] | None
    ) -> dict[str, Any]:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported.")
        page_count = len(reader.pages)
        if page_count > self.config.max_pages:
            raise ValueError("PDF exceeds configured max_pages.")
        page_numbers = _select_pages(requested_pages, page_count)
        pages: list[dict[str, Any]] = []
        warnings: list[str] = []
        for page_number in page_numbers:
            text = reader.pages[page_number - 1].extract_text() or ""
            if len(text) > self.config.max_chars_per_page:
                text = text[: self.config.max_chars_per_page]
                warnings.append(
                    f"page {page_number}: text truncated at max_chars_per_page"
                )
            if not text:
                warnings.append(
                    f"page {page_number}: no extractable text (OCR is not enabled)"
                )
            pages.append({"page_number": page_number, "text": text})
        return {
            "success": True,
            "source": source,
            "page_count": page_count,
            "pages": pages,
            "meta": {"warnings": warnings},
        }


def build_pdf_reader_tool(config: dict[str, Any], _runtime_deps: Any) -> PdfReaderTool:
    return PdfReaderTool(PdfReaderToolConfig.model_validate(config))


def _select_pages(requested: list[int] | None, page_count: int) -> list[int]:
    if requested is None:
        return list(range(1, page_count + 1))
    if not requested:
        raise ValueError("page_numbers must not be empty when provided.")
    unique_pages = list(dict.fromkeys(requested))
    invalid = [number for number in unique_pages if number < 1 or number > page_count]
    if invalid:
        raise ValueError(f"page_numbers out of range: {invalid}")
    return unique_pages


def _failure(source: str, error: str) -> dict[str, Any]:
    return {
        "success": False,
        "source": source,
        "page_count": None,
        "pages": [],
        "meta": {"warnings": [], "error": error},
    }
