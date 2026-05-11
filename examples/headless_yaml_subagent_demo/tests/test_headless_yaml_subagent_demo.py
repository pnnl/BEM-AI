from __future__ import annotations

from pathlib import Path

from automa_ai.config.agent_spec import YamlAgentSpec


BASE_DIR = Path(__file__).resolve().parents[1]


def test_headless_yaml_subagent_specs_are_valid() -> None:
    coordinator = YamlAgentSpec.from_yaml_file(BASE_DIR / "coordinator.yaml")
    analyst = YamlAgentSpec.from_yaml_file(
        BASE_DIR / "subagents" / "energy_results_analyst.yaml"
    )

    assert coordinator.agent_card["name"] == "HeadlessResultsCoordinator"
    assert analyst.agent_card["name"] == "EnergyResultsAnalyst"


def test_coordinator_rebases_yaml_agent_base_dir() -> None:
    coordinator = YamlAgentSpec.from_yaml_file(BASE_DIR / "coordinator.yaml")
    tools = coordinator.to_factory_kwargs()["tools_config"]

    assert tools["tools"][0]["type"] == "yaml_agent"
    assert tools["tools"][0]["config"]["base_dir"] == str(BASE_DIR / "subagents")


def test_analyst_uses_only_allowed_headless_subagent_surface() -> None:
    analyst = YamlAgentSpec.from_yaml_file(
        BASE_DIR / "subagents" / "energy_results_analyst.yaml"
    )
    tools = analyst.to_factory_kwargs()["tools_config"]

    assert analyst.mcp is None
    assert analyst.memory is None
    assert analyst.subagents == []
    assert [tool["type"] for tool in tools["tools"]] == ["run_python"]
    assert Path(tools["tools"][0]["config"]["workspace_root"]).resolve() == BASE_DIR
