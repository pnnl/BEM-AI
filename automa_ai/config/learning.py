from __future__ import annotations

from pydantic import BaseModel


class LearningWorkflowConfig(BaseModel):
    """MVP config for post-run learning workflow."""

    enabled: bool = False
    reflection_agent_spec_path: str = "examples/configs/specs/learning/reflection_agent.yaml"
    lesson_agent_spec_path: str = "examples/configs/specs/learning/lesson_agent.yaml"
    output_dir: str = "artifacts/learning_lessons"
