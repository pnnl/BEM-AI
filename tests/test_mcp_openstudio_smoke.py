from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from mcp import ClientSession
from mcp.client.sse import sse_client

from automa_ai.agents.agent_factory import AgentFactory
from examples.openstudio_mcp_demo.agent import (
    build_chatbot,
    build_openstudio_mcp_config,
)
from examples.openstudio_mcp_demo.openstudio_mcp_server.server import serve


MCP_HOST = "localhost"
MCP_PORT = 10210
MCP_URL = f"http://{MCP_HOST}:{MCP_PORT}/sse"


@pytest.fixture(scope="session", autouse=True)
def start_openstudio_mcp_server():
    from multiprocessing import Process
    import time

    process = Process(target=serve, args=(MCP_HOST, MCP_PORT, "sse"), daemon=True)
    process.start()
    time.sleep(2)
    yield
    process.terminate()


@pytest.mark.asyncio
async def test_openstudio_mcp_smoke_list_and_call_model_load() -> None:
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "model.load" in names
            assert "model.clone" in names
            assert "model.list_measures" in names
            assert "sim.run" in names

            result = await session.call_tool(
                name="model.load",
                arguments={"model_uri": "file:///tmp/dummy.osm"},
            )
            payload = result.structuredContent
            assert isinstance(payload, dict)
            assert payload["ok"] is True
            assert isinstance(payload["model_id"], str)


def test_openstudio_example_uses_agent_factory_with_mcp_config() -> None:
    mcp_config = build_openstudio_mcp_config()
    factory = build_chatbot(mcp_config)
    assert isinstance(factory, AgentFactory)
    assert factory.mcp_configs is not None
    assert "openstudio_mcp" in factory.mcp_configs


@pytest.mark.asyncio
async def test_openstudio_mcp_apply_add_daylighting_measure() -> None:
    env_path = Path("examples/openstudio_mcp_demo/.env")
    env_values = dotenv_values(env_path) if env_path.exists() else {}
    openstudio_path = (
        os.getenv("OPENSTUDIO_PATH", "").strip()
        or str(env_values.get("OPENSTUDIO_PATH", "")).strip()
    )
    if not openstudio_path or not Path(openstudio_path).exists():
        pytest.skip("OPENSTUDIO_PATH is not configured to a valid executable.")

    sample_model_uri = (
        Path("examples/openstudio_mcp_demo/resource/sample.osm")
        .resolve()
        .as_uri()
    )
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            load_result = await session.call_tool(
                name="model.load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            original_model_id = load_payload["model_id"]

            measures_result = await session.call_tool(
                name="model.list_measures",
                arguments={},
            )
            measures_payload = measures_result.structuredContent
            assert isinstance(measures_payload, dict)
            assert measures_payload["ok"] is True
            measures = measures_payload.get("measures", [])
            assert any(item.get("measure_id") == "add_daylighting" for item in measures)

            apply_result = await session.call_tool(
                name="model.apply_measure",
                arguments={
                    "model_id": original_model_id,
                    "measure_id": "add_daylighting",
                    "args": {},
                },
            )
            apply_payload = apply_result.structuredContent
            assert isinstance(apply_payload, dict)
            assert apply_payload["ok"] is True
            assert isinstance(apply_payload["model_id"], str)
            assert apply_payload["model_id"] != original_model_id
            assert isinstance(apply_payload.get("changes", []), list)
            assert any("daylight" in str(item).lower() for item in apply_payload.get("changes", []))

            validate_result = await session.call_tool(
                name="model.validate",
                arguments={"model_id": apply_payload["model_id"]},
            )
            validate_payload = validate_result.structuredContent
            assert isinstance(validate_payload, dict)
            assert validate_payload["ok"] is True


@pytest.mark.asyncio
async def test_openstudio_mcp_simulation_flow_with_sample_model() -> None:
    sample_model_uri = (
        Path("examples/openstudio_mcp_demo/resource/sample.osm")
        .resolve()
        .as_uri()
    )
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            load_result = await session.call_tool(
                name="model.load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            model_id = load_payload["model_id"]

            run_result = await session.call_tool(
                name="sim.run",
                arguments={"model_id": model_id, "run_mode": "sizing", "options": {}},
            )
            run_payload = run_result.structuredContent
            assert isinstance(run_payload, dict)

            # If OPENSTUDIO_PATH is not configured, the tool should fail fast with invalid_state.
            if not run_payload.get("ok", False):
                assert run_payload["error"]["type"] == "invalid_state"
                return

            # Otherwise, the job should run asynchronously and eventually reach a terminal state.
            job_id = run_payload["job_id"]
            assert isinstance(job_id, str)

            final_state = None
            for _ in range(120):
                status_result = await session.call_tool(
                    name="sim.status",
                    arguments={"job_id": job_id},
                )
                status_payload = status_result.structuredContent
                assert isinstance(status_payload, dict)
                assert status_payload["ok"] is True
                final_state = status_payload["state"]
                if final_state in {"SUCCEEDED", "FAILED"}:
                    break
                await asyncio.sleep(0.5)

            assert final_state in {"SUCCEEDED", "FAILED"}


@pytest.mark.asyncio
async def test_openstudio_mcp_real_simulation_with_sample_model() -> None:
    env_path = Path("examples/openstudio_mcp_demo/.env")
    env_values = dotenv_values(env_path) if env_path.exists() else {}
    openstudio_path = (
        os.getenv("OPENSTUDIO_PATH", "").strip()
        or str(env_values.get("OPENSTUDIO_PATH", "")).strip()
    )
    if not openstudio_path or not Path(openstudio_path).exists():
        pytest.skip("OPENSTUDIO_PATH is not configured to a valid executable.")

    sample_model_uri = (
        Path("examples/openstudio_mcp_demo/resource/sample.osm")
        .resolve()
        .as_uri()
    )
    workspace_root = Path(".openstudio_mcp_workspace").resolve()
    existing_sqls = {str(p.resolve()) for p in workspace_root.rglob("run/eplusout.sql")} if workspace_root.exists() else set()
    started_at = time.time()

    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            load_result = await session.call_tool(
                name="model.load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            model_id = load_payload["model_id"]

            run_result = await session.call_tool(
                name="sim.run",
                arguments={"model_id": model_id, "run_mode": "sizing", "options": {}},
            )
            run_payload = run_result.structuredContent
            assert isinstance(run_payload, dict)
            assert run_payload["ok"] is True
            job_id = run_payload["job_id"]

            final_state = None
            for _ in range(360):
                status_result = await session.call_tool(
                    name="sim.status",
                    arguments={"job_id": job_id},
                )
                status_payload = status_result.structuredContent
                assert isinstance(status_payload, dict)
                assert status_payload["ok"] is True
                final_state = status_payload["state"]
                if final_state in {"SUCCEEDED", "FAILED"}:
                    break
                await asyncio.sleep(1.0)

            assert final_state == "SUCCEEDED", status_payload

            artifacts_result = await session.call_tool(
                name="sim.artifacts",
                arguments={"job_id": job_id},
            )
            artifacts_payload = artifacts_result.structuredContent
            assert isinstance(artifacts_payload, dict)
            assert artifacts_payload["ok"] is True
            assert isinstance(artifacts_payload["sql_id"], str)
            assert isinstance(artifacts_payload["logs_id"], str)

            query_result = await session.call_tool(
                name="results.query",
                arguments={
                    "sql_id": artifacts_payload["sql_id"],
                    "query_type": "sizing_summary",
                    "params": {},
                },
            )
            query_payload = query_result.structuredContent
            assert isinstance(query_payload, dict)
            assert query_payload["ok"] is True
            summary_data = query_payload["data"]
            assert "annual_end_use_fuel_gj" in summary_data
            assert "design_day_end_use_fuel_j" in summary_data
            assert "annual_eui" in summary_data
            assert summary_data["annual_eui"]["total_site_energy_gj"] > 0.0

    assert workspace_root.exists()
    new_sqls = {str(p.resolve()) for p in workspace_root.rglob("run/eplusout.sql")}
    created_sqls = new_sqls - existing_sqls
    assert created_sqls, "No new eplusout.sql found in .openstudio_mcp_workspace."
    assert any(Path(p).stat().st_mtime >= started_at for p in map(Path, created_sqls))
