from __future__ import annotations

from typing import Any


TRUSTED_PROMOTION_TARGETS = {
    "knowledge_base",
    "skill",
    "sdk_index",
    "mcp_tool",
    "mcp_measure",
    "eval",
}


def build_promotion_record(candidate: dict[str, Any], target: str, reviewer: str) -> dict[str, Any]:
    if target not in TRUSTED_PROMOTION_TARGETS:
        raise ValueError(f"Unsupported promotion target: {target}")
    if not candidate.get("eval_case_ids"):
        raise ValueError("Promoted assets must reference at least one eval case.")
    return {
        "status": "promoted",
        "target": target,
        "reviewer": reviewer,
        "candidate": candidate,
    }

