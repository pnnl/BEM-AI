from automa_ai.config.tools import ToolSpec, ToolsConfig


def test_tools_config_validation() -> None:
    cfg = ToolsConfig.from_dict(
        {
            "tools": [
                {"type": "web_search", "config": {"provider": "opensource"}},
            ]
        }
    )
    assert len(cfg.tools) == 1
    assert cfg.tools[0].type == "web_search"


def test_tool_spec_defaults() -> None:
    spec = ToolSpec.model_validate({"type": "web_search"})
    assert spec.config == {}
