from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HarnessConfig:
    root: Path
    mcp_transport: str = "sse"
    enable_learning_capture: bool = True
    trusted_asset_mode: str = "reviewed_only"

