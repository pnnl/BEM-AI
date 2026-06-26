from __future__ import annotations

import json
from pathlib import Path

from automa_ai.config.agent_spec import YamlAgentSpec

from examples.openstudio_ai.learning.developer_pipeline.run_pipeline import (
    run_developer_learning_pipeline,
)


def test_developer_learning_pipeline_writes_candidate_lesson(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    review_queue = tmp_path / "review_queue"
    logs_dir.mkdir()
    failure = {
        "stderr": "OpenStudio SDK error: Surface.getAzimuth returned radians but script treated it as degrees.",
        "script": {
            "code": "azimuth = surface.getAzimuth()  # incorrectly assumed degrees",
        },
    }
    (logs_dir / "python_script_failure_experience.jsonl").write_text(
        json.dumps(failure) + "\n",
        encoding="utf-8",
    )

    writes = run_developer_learning_pipeline(
        logs_dir=logs_dir,
        review_queue=review_queue,
        limit=5,
    )

    assert len(writes) == 1
    candidate = json.loads(writes[0].path.read_text(encoding="utf-8"))
    assert candidate["status"] == "candidate"
    assert candidate["review_required"] is True
    assert candidate["target"]["asset"] == "knowledge/openstudio_sdk_wiki/sdk_geometry.md"
    assert candidate["recommended_eval"]["expected_behavior"]
    assert candidate["evidence"][0]["line_number"] == 1


def test_developer_learning_agent_yaml_matches_automa_ai_spec() -> None:
    spec_path = Path(
        "examples/openstudio_ai/learning/developer_agent/developer_learning_agent.yaml"
    )

    spec = YamlAgentSpec.from_yaml_file(spec_path)
    instructions = spec.resolve_instructions()

    assert spec.agent_card["name"] == "OpenStudio Developer Learning Agent"
    assert spec.runtime.agent_type.value == "langgraph-chat"
    assert "Create candidates only." in instructions
    assert "Do not promote trusted assets." in instructions
    assert "review queue" in instructions
