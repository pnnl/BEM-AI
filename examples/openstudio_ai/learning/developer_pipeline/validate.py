from __future__ import annotations

from typing import Any


def attach_eval_reference(candidate: dict[str, Any], eval_case_id: str) -> dict[str, Any]:
    next_candidate = dict(candidate)
    refs = list(next_candidate.get("eval_case_ids", []))
    refs.append(eval_case_id)
    next_candidate["eval_case_ids"] = sorted(set(refs))
    next_candidate["status"] = "validated"
    return next_candidate

