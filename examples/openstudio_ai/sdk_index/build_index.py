from __future__ import annotations

from pathlib import Path


def build_sdk_index(source_dir: str | Path, output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path

