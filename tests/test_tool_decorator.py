import pytest
from pydantic import BaseModel

from automa_ai.tools import tool
from automa_ai.tools.registry import CUSTOM_TOOL_REGISTRY, build_langchain_tools
from automa_ai.config.tools import ToolSpec

def test_simple_tool_registration():
    """Test that @tool decorator registers tools."""
    @tool
    def test_tool(text: str) -> str:
        """Test tool."""
        return text.upper()

    assert test_tool.__tool_name__ == "test_tool"
    assert f"{__name__}.{test_tool.__name__}" in CUSTOM_TOOL_REGISTRY._builders


def test_tool_with_custom_name():
    """Test @tool with custom name."""
    @tool(name="custom_name")
    def original_name(x: int) -> int:
        """Tool with custom name."""
        return x * 2
    
    print(original_name.__name__)

    assert original_name.__tool_name__ == f"custom_name"
    assert f"{__name__}.{original_name.__name__}" in CUSTOM_TOOL_REGISTRY._builders


def test_tool_with_config_schema():
    """Test @tool with config schema."""
    class MyConfig(BaseModel):
        api_key: str
        timeout: int = 30

    @tool(config_schema=MyConfig)
    def configured_tool(query: str, *, config: MyConfig) -> dict:
        """Tool that requires config."""
        return {"query": query, "api_key": config.api_key}

    assert f"{__name__}.configured_tool" in CUSTOM_TOOL_REGISTRY._builders


@pytest.mark.asyncio
async def test_async_tool():
    """Test async tool invocation."""
    @tool
    async def async_tool(value: str) -> dict:
        """Async test tool."""
        return {"result": value}

    spec = ToolSpec(type=f"{__name__}.async_tool")
    built_tool = CUSTOM_TOOL_REGISTRY.build(spec)

    result = await built_tool.invoke({"value": "test"})
    assert result == {"result": "test"}


@pytest.mark.asyncio
async def test_sync_tool():
    """Test sync tool invocation."""
    @tool
    def sync_tool(x: int, y: int) -> dict:
        """Sync test tool."""
        return {"sum": x + y}

    spec = ToolSpec(type=f"{__name__}.sync_tool")
    built_tool = CUSTOM_TOOL_REGISTRY.build(spec)

    result = await built_tool.invoke({"x": 5, "y": 3})
    assert result == {"sum": 8}


@pytest.mark.asyncio
async def test_tool_with_config_injection():
    """Test that config is properly injected."""
    class ApiConfig(BaseModel):
        api_key: str

    @tool(config_schema=ApiConfig)
    def api_tool(query: str, *, config: ApiConfig) -> dict:
        """Tool using config."""
        return {"query": query, "key": config.api_key}

    spec = ToolSpec(type=f"{__name__}.api_tool", config={"api_key": "secret123"})
    built_tool = CUSTOM_TOOL_REGISTRY.build(spec)

    result = await built_tool.invoke({"query": "test"})
    assert result["query"] == "test"
    assert result["key"] == "secret123"


def test_build_langchain_tools_with_custom_tools():
    """Test build_langchain_tools includes custom tools."""
    @tool
    def my_custom_tool(value: str) -> str:
        """Custom tool for testing."""
        return value

    tool_specs = [ToolSpec(type=f"{__name__}.my_custom_tool")]
    tools = build_langchain_tools(tool_specs)

    assert len(tools) == 1
    assert tools[0].name == f"my_custom_tool"


def test_auto_import_with_dotted_path():
    """Test that dotted paths trigger auto-import."""

    spec = ToolSpec(type="mymodule.tools.my_tool")

    # Should raise ValueError since module doesn't exist
    # but it should try the import logic
    with pytest.raises(ModuleNotFoundError, match="No module named 'mymodule'"):
        CUSTOM_TOOL_REGISTRY.build(spec)


def test_tool_schema_inference():
    """Test that tool schemas are properly inferred."""
    @tool(parse_docstring=True)
    def documented_tool(query: str, limit: int = 10) -> dict:
        """Search for something.

        Args:
            query: The search query
            limit: Maximum results
        """
        return {"query": query, "limit": limit}

    spec = ToolSpec(type=f"{__name__}.documented_tool")
    built_tool = CUSTOM_TOOL_REGISTRY.build(spec)

    # Check schema was created
    schema = built_tool.args_schema.model_json_schema()
    assert "query" in schema["properties"]
    assert "limit" in schema["properties"]
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["properties"]["limit"]["type"] == "integer"
