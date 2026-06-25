from __future__ import annotations

from pathlib import Path

from examples.openstudio_ai.harness.artifact_types import HarnessAssets


DEVELOPER_ONLY_SKILL_FILES = {
    "HVAC_CHILD_SKILL_MANAGEMENT.md",
}


def discover_harness_assets(root: Path) -> HarnessAssets:
    root = root.resolve()
    prompts_dir = root / "prompts"
    skills_dir = root / "skills"
    return HarnessAssets(
        root=root,
        prompt_contracts=sorted(prompts_dir.glob("*.md")),
        skill_files=sorted(
            path for path in skills_dir.glob("*.md") if path.name not in DEVELOPER_ONLY_SKILL_FILES
        ),
        mcp_entrypoint=root / "mcp" / "server.py",
        blackboard_schema=root / "blackboard" / "schemas" / "workflow_state.schema.json",
        learning_event_log=root / "logs" / "learning_events.jsonl",
        knowledge_roots=[root / "knowledge"],
        sdk_index_roots=[root / "sdk_index" / "index", root / "sdk_index" / "graph"],
    )
