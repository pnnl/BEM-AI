from __future__ import annotations

from typing import Any


def propose_candidate_measure(script_summary: dict[str, Any], *, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "candidate",
        "source": "harness_pipeline",
        "summary": script_summary.get("summary", ""),
        "script_excerpt": script_summary.get("script_excerpt", ""),
        "review_required": True,
    }

