from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automa_ai.blackboard.store import BlackboardStore
from automa_ai.config.agent_spec import YamlAgentSpec

logger = logging.getLogger(__name__)


def build_review_payload(
    *,
    query: str,
    final_response: Any,
    response_type: str,
    session_id: str,
    task_id: str,
    blackboard_store: BlackboardStore | None = None,
) -> dict[str, Any]:
    """Build a compact post-run payload for reflection/lesson extraction.

    Intentionally MVP-level: derived from artifacts already available in the
    normal runtime path.
    """

    blackboard_snapshot = None
    if blackboard_store:
        try:
            doc = blackboard_store.load(session_id)
            blackboard_snapshot = {
                "revision": doc.revision,
                "updated_at": doc.updated_at.isoformat(),
                "data": doc.data,
            }
        except Exception as exc:  # best-effort only
            logger.debug("Unable to load blackboard snapshot for learning payload: %s", exc)

    normalized_response = _normalize_final_response(final_response)

    validator_failures = []
    errors = []
    task_status = "completed"
    # user_correction_signal = None  # Reserved for future extension.

    if isinstance(normalized_response, dict):
        if isinstance(normalized_response.get("validator_failures"), list):
            validator_failures = normalized_response["validator_failures"]
        if isinstance(normalized_response.get("errors"), list):
            errors = normalized_response["errors"]
        if isinstance(normalized_response.get("status"), str):
            task_status = normalized_response["status"]

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "final_response": normalized_response,
        "task_status": task_status,
        "key_execution_summary": {
            "response_type": response_type,
            "session_id": session_id,
            "task_id": task_id,
        },
        "validator_failures": validator_failures,
        "errors": errors,
        "blackboard_snapshot": blackboard_snapshot,
        # "user_correction_signal": user_correction_signal,  # Reserved for future extension.
    }


async def run_learning_workflow(
    *,
    payload: dict[str, Any],
    reflection_spec_path: str,
    lesson_spec_path: str,
    output_dir: str,
    session_id: str,
) -> None:
    """Execute reflection -> lesson extraction in best-effort background mode."""

    reflection_spec = YamlAgentSpec.from_yaml_file(reflection_spec_path)
    reflection_agent = reflection_spec.to_agent_factory().get_agent()

    reflection_query = _json_prompt("Run reflection on this completed task payload", payload)
    reflection_raw = await reflection_agent.invoke(reflection_query, f"{session_id}-reflection")
    reflection_text = _extract_response_text(reflection_raw)

    lesson_spec = YamlAgentSpec.from_yaml_file(lesson_spec_path)
    lesson_agent = lesson_spec.to_agent_factory().get_agent()

    lesson_query = _json_prompt(
        "Convert this reflection into compact structured lessons",
        {"payload": payload, "reflection": reflection_text},
    )
    lesson_raw = await lesson_agent.invoke(lesson_query, f"{session_id}-lesson")
    lesson_text = _extract_response_text(lesson_raw)

    _persist_lesson(
        output_dir=output_dir,
        session_id=session_id,
        payload=payload,
        reflection_output=reflection_text,
        lesson_output=lesson_text,
    )


def _extract_response_text(response: Any) -> Any:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        messages = response.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content is not None:
                return content
            if isinstance(last, dict):
                return last.get("content", str(last))
        return response
    return str(response)


def _normalize_final_response(final_response: Any) -> Any:
    """Normalize final output into a compact, JSON-safe payload."""
    if isinstance(final_response, (str, int, float, bool)) or final_response is None:
        return final_response
    if isinstance(final_response, dict):
        messages = final_response.get("messages")
        if isinstance(messages, list) and messages:
            last_content = _extract_message_content(messages[-1])
            return {
                "kind": "langgraph_messages",
                "message_count": len(messages),
                "last_message": last_content,
            }
        return final_response
    if isinstance(final_response, list):
        return [_normalize_final_response(item) for item in final_response]
    return _extract_message_content(final_response)


def _extract_message_content(message: Any) -> Any:
    if isinstance(message, dict):
        if "content" in message:
            return message["content"]
        return {k: _extract_message_content(v) for k, v in message.items()}
    content = getattr(message, "content", None)
    if content is not None:
        return content
    model_dump = getattr(message, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict) and "content" in dumped:
            return dumped["content"]
        return dumped
    return str(message)


def _json_prompt(prefix: str, payload: dict[str, Any]) -> str:
    return f"{prefix}.\n\nPayload:\n{json.dumps(payload, ensure_ascii=False)}"


def _persist_lesson(
    *,
    output_dir: str,
    session_id: str,
    payload: dict[str, Any],
    reflection_output: Any,
    lesson_output: Any,
) -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(output_dir) / f"{session_id}-{stamp}.lesson.json"

    bundle = {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "review_payload": payload,
        "reflection_output": reflection_output,
        "lesson_output": lesson_output,
    }
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Learning lesson persisted to %s", out_path)
