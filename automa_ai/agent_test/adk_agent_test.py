import time
from multiprocessing import Process

import pytest
from google.adk.models.lite_llm import LiteLlm

from agents.adk_agent import GenericADKAgent
from common import prompts
from mcp_servers.server import serve

MCP_HOST = "localhost"
MCP_PORT = 10100
MCP_URL = f"http://{MCP_HOST}:{MCP_PORT}/sse"


@pytest.fixture(scope="session", autouse=True)
def start_mcp_server():
    """Start MCP server in a subprocess for integration testing."""
    process = Process(target=serve, args=(MCP_HOST, MCP_PORT, "sse"), daemon=True)
    process.start()
    time.sleep(5)  # give time for server to boot and load vectorstore
    yield
    process.terminate()


@pytest.mark.asyncio
async def test_geo_modeler_agent_stream():
    # Arrange
    agent = GenericADKAgent(
        agent_name="energy_model_geometry_agent",
        description="Modify energy model geometry including window to wall ratio",
        instructions=prompts.GEOMETRY_COT_INSTRUCTIONS,
        chat_model=LiteLlm(model="ollama_chat/llama3.1:8b"),
    )

    # Mock the MCP tool loading if needed to isolate from external services
    await agent.init_agent()

    # Provide a dummy but valid input
    test_query = (
        "Adjust the window to wall ratio to 0.4 for the elementary school model"
    )
    test_context_id = "test-session-id"
    test_task_id = "test-task-id"

    # Act
    results = []
    async for chunk in agent.stream(test_query, test_context_id, test_task_id):
        results.append(chunk)
        print(chunk)
        if chunk.get("is_task_complete"):
            break

    # Assert
    assert results, "Agent returned no results"
    final = results[-1]
    assert final["is_task_complete"] is True
    assert "content" in final
    assert final["content"] is not None


@pytest.mark.asyncio
async def test_template_modeler_agent_stream():
    # Arrange
    agent = GenericADKAgent(
        agent_name="energy_model_geometry_agent",
        description="Load energy model template based on building type",
        instructions=prompts.GEOMETRY_COT_INSTRUCTIONS,
        chat_model=LiteLlm(model="ollama_chat/llama3.1:8b"),
    )

    # Mock the MCP tool loading if needed to isolate from external services
    await agent.init_agent()

    # Provide a dummy but valid input
    test_query = "Load energy model template for school"
    test_context_id = "test-session-id"
    test_task_id = "test-task-id"

    # Act
    results = []
    async for chunk in agent.stream(test_query, test_context_id, test_task_id):
        results.append(chunk)
        print(chunk)
        if chunk.get("is_task_complete"):
            break

    # Assert
    assert results, "Agent returned no results"
    final = results[-1]
    assert final["is_task_complete"] is True
    assert "content" in final
    assert final["content"] is not None
