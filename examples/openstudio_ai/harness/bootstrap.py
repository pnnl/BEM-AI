from __future__ import annotations

from pathlib import Path

from examples.openstudio_ai.harness.artifact_types import HarnessAssets
from examples.openstudio_ai.harness.loader import load_harness_assets


def build_harness(root: str | Path) -> HarnessAssets:
    """Return the file-backed harness assets for an adapter to install."""
    return load_harness_assets(root)

