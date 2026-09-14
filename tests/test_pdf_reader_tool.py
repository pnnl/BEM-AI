from pathlib import Path

import pytest
from pypdf import PdfWriter

from automa_ai.tools import DEFAULT_TOOL_REGISTRY
from automa_ai.tools.pdf_reader.config import PdfReaderToolConfig
from automa_ai.tools.pdf_reader.tool import PdfReaderTool


class FakePage:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self) -> str:
        return self.text


class FakeReader:
    is_encrypted = False

    def __init__(self, _path: Path):
        self.pages = [FakePage("first page"), FakePage(""), FakePage("third page")]


def _tool(tmp_path: Path, **config: object) -> PdfReaderTool:
    return PdfReaderTool(
        PdfReaderToolConfig.model_validate({"upload_root": str(tmp_path), **config})
    )


def test_registry_build_includes_pdf_reader() -> None:
    assert "pdf_reader" in DEFAULT_TOOL_REGISTRY._builders


@pytest.mark.asyncio
async def test_extracts_requested_pages_and_preserves_empty_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr("automa_ai.tools.pdf_reader.tool.PdfReader", FakeReader)

    result = await _tool(tmp_path).invoke(
        {"source": str(source), "page_numbers": [3, 2]}
    )

    assert result["success"] is True
    assert result["page_count"] == 3
    assert result["pages"] == [
        {"page_number": 3, "text": "third page"},
        {"page_number": 2, "text": ""},
    ]
    assert (
        "page 2: no extractable text (OCR is not enabled)" in result["meta"]["warnings"]
    )


@pytest.mark.asyncio
async def test_rejects_paths_outside_upload_root(tmp_path: Path) -> None:
    result = await _tool(tmp_path).invoke({"source": "/tmp/report.pdf"})

    assert result["success"] is False
    assert result["pages"] == []
    assert result["meta"]["error"] == "Local PDF source must be inside upload_root."


@pytest.mark.asyncio
async def test_rejects_invalid_requested_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr("automa_ai.tools.pdf_reader.tool.PdfReader", FakeReader)

    result = await _tool(tmp_path).invoke({"source": str(source), "page_numbers": [4]})

    assert result["success"] is False
    assert result["meta"]["error"] == "page_numbers out of range: [4]"


@pytest.mark.asyncio
async def test_extracts_a_real_blank_pdf_page(tmp_path: Path) -> None:
    source = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as stream:
        writer.write(stream)

    result = await _tool(tmp_path).invoke({"source": str(source)})

    assert result["success"] is True
    assert result["pages"] == [{"page_number": 1, "text": ""}]


class FakeS3Client:
    def __init__(self, content: bytes):
        self.content = content
        self.head_calls: list[dict[str, str]] = []
        self.download_calls: list[tuple[str, str]] = []

    def head_object(self, **kwargs: str) -> dict[str, int]:
        self.head_calls.append(kwargs)
        return {"ContentLength": len(self.content)}

    def download_fileobj(self, bucket: str, key: str, file_object: object) -> None:
        self.download_calls.append((bucket, key))
        file_object.write(self.content)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_downloads_allowlisted_s3_source_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeS3Client(b"placeholder")
    opened_paths: list[Path] = []

    class TrackingReader(FakeReader):
        def __init__(self, path: Path):
            opened_paths.append(Path(path))
            super().__init__(path)

    monkeypatch.setattr("automa_ai.tools.pdf_reader.tool.PdfReader", TrackingReader)
    monkeypatch.setattr(
        "automa_ai.tools.pdf_reader.tool.boto3.client", lambda *_args, **_kwargs: client
    )
    tool = _tool(
        tmp_path,
        s3={
            "enabled": True,
            "allowed_buckets": ["bem-ai-documents"],
            "allowed_key_prefixes": ["uploads/"],
        },
    )

    result = await tool.invoke({"source": "s3://bem-ai-documents/uploads/report.pdf"})

    assert result["success"] is True
    assert result["source"] == "s3://bem-ai-documents/uploads/report.pdf"
    assert client.head_calls == [
        {"Bucket": "bem-ai-documents", "Key": "uploads/report.pdf"}
    ]
    assert client.download_calls == [("bem-ai-documents", "uploads/report.pdf")]
    assert opened_paths and not opened_paths[0].exists()


@pytest.mark.asyncio
async def test_rejects_non_allowlisted_s3_bucket(tmp_path: Path) -> None:
    tool = _tool(
        tmp_path,
        s3={"enabled": True, "allowed_buckets": ["bem-ai-documents"]},
    )

    result = await tool.invoke({"source": "s3://other-bucket/report.pdf"})

    assert result["success"] is False
    assert result["meta"]["error"] == "S3 bucket is not allowed."


@pytest.mark.asyncio
async def test_rejects_s3_query_parameters(tmp_path: Path) -> None:
    tool = _tool(
        tmp_path,
        s3={"enabled": True, "allowed_buckets": ["bem-ai-documents"]},
    )

    result = await tool.invoke({"source": "s3://bem-ai-documents/report.pdf?version=1"})

    assert result["success"] is False
    assert "must not include parameters" in result["meta"]["error"]


def test_s3_config_requires_allowlist_when_enabled() -> None:
    with pytest.raises(ValueError, match="allowed_buckets"):
        PdfReaderToolConfig.model_validate({"s3": {"enabled": True}})
