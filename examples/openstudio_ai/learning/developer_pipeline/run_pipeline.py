from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
DEFAULT_REVIEW_QUEUE = Path(__file__).resolve().parents[1] / "review_queue"


@dataclass(frozen=True)
class CandidateWrite:
    """Candidate asset written by the developer learning pipeline."""

    candidate_id: str
    path: Path


def run_developer_learning_pipeline(
    *,
    logs_dir: Path = DEFAULT_LOGS_DIR,
    review_queue: Path = DEFAULT_REVIEW_QUEUE,
    limit: int = 10,
) -> list[CandidateWrite]:
    """Read raw OpenStudio AI logs and write review-queue candidate lessons.

    This is the deterministic implementation of the developer learning curation
    pass. It does not promote assets. It converts raw evidence into candidate
    JSON files that a modeler/developer can review, validate with evals, and
    then promote.
    """
    events = _collect_learning_events(logs_dir=logs_dir, limit=limit)
    review_queue.mkdir(parents=True, exist_ok=True)

    writes: list[CandidateWrite] = []
    for event in events:
        candidate = _build_candidate_lesson(event)
        path = review_queue / f"{candidate['candidate_id']}.json"
        path.write_text(json.dumps(candidate, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        writes.append(CandidateWrite(candidate_id=candidate["candidate_id"], path=path))
    return writes


def _collect_learning_events(*, logs_dir: Path, limit: int) -> list[dict[str, Any]]:
    """Collect candidate-worthy events from known OpenStudio AI log files."""
    events: list[dict[str, Any]] = []
    for path in [
        logs_dir / "python_script_failure_experience.jsonl",
        logs_dir / "telemetry.jsonl",
    ]:
        if not path.exists():
            continue
        for line_number, payload in _read_jsonl(path):
            event = _normalize_event(path, line_number, payload)
            if event is not None:
                events.append(event)
            if len(events) >= limit:
                return events
    return events


def _read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    """Return JSON objects from a JSONL file, skipping malformed lines."""
    rows: list[tuple[int, dict[str, Any]]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append((index, payload))
    return rows


def _normalize_event(path: Path, line_number: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Convert heterogeneous log records into one candidate-event shape."""
    if path.name == "python_script_failure_experience.jsonl":
        stderr = str(payload.get("stderr") or payload.get("error") or "")
        code = payload.get("script", {}).get("code") if isinstance(payload.get("script"), dict) else None
        summary = stderr.splitlines()[0] if stderr else "Python script failure captured."
        return {
            "event_type": "python_script_failure",
            "summary": summary[:240],
            "detail": stderr[:2000],
            "script_excerpt": str(code or "")[:2000],
            "source_path": str(path),
            "line_number": line_number,
            "raw": payload,
        }

    attributes = payload.get("attributes")
    if path.name == "telemetry.jsonl" and isinstance(attributes, dict):
        completion = attributes.get("gen_ai.completion")
        if isinstance(completion, str) and _looks_like_learning_signal(completion):
            return {
                "event_type": "telemetry_learning_signal",
                "summary": completion.splitlines()[0][:240],
                "detail": completion[:2000],
                "source_path": str(path),
                "line_number": line_number,
                "raw": payload,
            }
    return None


def _looks_like_learning_signal(text: str) -> bool:
    """Detect telemetry outputs that are likely to contain reusable lessons."""
    lowered = text.lower()
    markers = [
        "warning",
        "failed",
        "error",
        "ruled out",
        "likely cause",
        "recommended next step",
        "sdk",
        "openstudio",
    ]
    return any(marker in lowered for marker in markers)


def _build_candidate_lesson(event: dict[str, Any]) -> dict[str, Any]:
    """Build a reviewable lesson candidate from one normalized evidence event."""
    candidate_id = _candidate_id(event)
    return {
        "candidate_id": candidate_id,
        "type": "knowledge_base_lesson",
        "status": "candidate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": event["summary"],
        "evidence": [
            {
                "source": event["source_path"],
                "line_number": event["line_number"],
                "event_type": event["event_type"],
                "detail": event.get("detail", ""),
                "script_excerpt": event.get("script_excerpt", ""),
            }
        ],
        "target": _suggest_target(event),
        "recommended_eval": _suggest_eval(event),
        "reviewer_checklist": [
            "Confirm the event reflects a repeatable OpenStudio AI lesson.",
            "Confirm target asset is correct.",
            "Add or update an eval before promotion.",
            "Promote only after modeler/developer review.",
        ],
        "confidence": "candidate",
        "review_required": True,
    }


def _suggest_target(event: dict[str, Any]) -> dict[str, str]:
    """Suggest where a reviewed lesson might eventually be promoted."""
    detail = f"{event.get('summary', '')} {event.get('detail', '')}".lower()
    if "schedule" in detail:
        asset = "knowledge/openstudio_sdk_wiki/sdk_schedules.md"
    elif "hvac" in detail or "airloop" in detail or "coil" in detail:
        asset = "knowledge/openstudio_sdk_wiki/sdk_hvac.md"
    elif "surface" in detail or "geometry" in detail or "azimuth" in detail:
        asset = "knowledge/openstudio_sdk_wiki/sdk_geometry.md"
    elif "sql" in detail or "result" in detail or "simulation" in detail:
        asset = "knowledge/openstudio_sdk_wiki/sdk_simulation_results.md"
    else:
        asset = "knowledge/openstudio_sdk_recipes.md"
    return {"asset": asset, "change_type": "append_reviewed_lesson"}


def _suggest_eval(event: dict[str, Any]) -> dict[str, Any]:
    """Suggest a minimal eval case that should gate promotion."""
    return {
        "category": event["event_type"],
        "prompt": f"Handle an OpenStudio workflow involving: {event['summary']}",
        "expected_behavior": [
            "Identifies the relevant OpenStudio SDK or MCP boundary.",
            "Avoids repeating the captured failure pattern.",
            "States assumptions and validation checks.",
        ],
    }


def _candidate_id(event: dict[str, Any]) -> str:
    """Build a stable filename-friendly candidate id from evidence metadata."""
    stem = re.sub(r"[^a-z0-9]+", "_", event["summary"].lower()).strip("_")[:60]
    if not stem:
        stem = event["event_type"]
    return f"{event['event_type']}_{event['line_number']}_{stem}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create OpenStudio AI learning candidates from logs.")
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR)
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    writes = run_developer_learning_pipeline(
        logs_dir=args.logs_dir,
        review_queue=args.review_queue,
        limit=args.limit,
    )
    for write in writes:
        print(f"Wrote {write.path}")
    if not writes:
        print("No candidate-worthy learning events found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
