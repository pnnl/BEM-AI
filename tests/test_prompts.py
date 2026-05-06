from pathlib import Path

from automa_ai.prompts import RESPONSE_PROMPT, SUBAGENT_PROMPT
from automa_ai.config.agent_spec import YamlAgentSpec


def test_prompt_templates_are_exported() -> None:
    assert "RESPONSE CONTRACT" in RESPONSE_PROMPT
    assert "{subagents}" in SUBAGENT_PROMPT
    assert "{query}" in SUBAGENT_PROMPT
    assert "yaml_agent" in SUBAGENT_PROMPT
    assert "Do not invent YAML paths" in SUBAGENT_PROMPT
    assert "must not define nested subagents" in SUBAGENT_PROMPT
    assert "When to spawn a headless subagent" in SUBAGENT_PROMPT
    assert "Computing annual totals from the monthly results" in SUBAGENT_PROMPT
    assert "focused subtask" in SUBAGENT_PROMPT


def test_headless_subagent_template_is_constrained_yaml_spec() -> None:
    template_path = Path("docs/templates/headless_subagent.yaml")
    spec = YamlAgentSpec.from_yaml_file(template_path)

    assert spec.mcp is None
    assert spec.memory is None
    assert spec.subagents == []
    assert spec.tools is None
    assert "Do not create or call additional subagents" in spec.resolve_instructions()
