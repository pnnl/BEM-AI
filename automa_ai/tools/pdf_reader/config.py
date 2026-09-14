"""Configuration for the PDF reader default tool."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class S3PdfReaderConfig(BaseModel):
    """Allowlist and transfer controls for S3 PDF sources."""

    enabled: bool = False
    allowed_buckets: list[str] = Field(default_factory=list)
    allowed_key_prefixes: list[str] = Field(default_factory=list)
    region_name: str | None = None

    @model_validator(mode="after")
    def validate_allowlists(self) -> "S3PdfReaderConfig":
        if self.enabled and not self.allowed_buckets:
            raise ValueError("s3.allowed_buckets is required when S3 is enabled.")
        for bucket in self.allowed_buckets:
            if not bucket or "/" in bucket or "\\" in bucket:
                raise ValueError("s3.allowed_buckets must contain bucket names only.")
        for prefix in self.allowed_key_prefixes:
            if not prefix or prefix.startswith("/") or "\\" in prefix:
                raise ValueError(
                    "s3.allowed_key_prefixes must be relative S3 prefixes."
                )
        return self


class PdfReaderToolConfig(BaseModel):
    """Runtime limits and permitted source locations for PDF extraction."""

    upload_root: str = "."
    max_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    max_pages: int = Field(default=200, ge=1, le=10_000)
    max_chars_per_page: int = Field(default=100_000, ge=1, le=5_000_000)
    s3: S3PdfReaderConfig = Field(default_factory=S3PdfReaderConfig)

    @model_validator(mode="after")
    def normalize_upload_root(self) -> "PdfReaderToolConfig":
        self.upload_root = str(Path(self.upload_root).resolve())
        return self
