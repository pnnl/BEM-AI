from __future__ import annotations

import asyncio
from copy import deepcopy
import os
import socket
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from mcp import ClientSession
from mcp.client.sse import sse_client

from automa_ai.blackboard.models import BlackboardPatch
from automa_ai.blackboard.schema import BlackboardSchemaRegistry
from automa_ai.blackboard.store import create_blackboard_store
from automa_ai.common.agent_registry import A2AAgentServer
from automa_ai.config.agent_spec import load_a2a_server_from_yaml
from automa_ai.skills.manager import SkillManager
from examples.openstudio_ai.agent import (
    build_openstudio_mcp_config,
    load_openstudio_agent_spec,
)
from examples.openstudio_ai.openstudio_mcp.server import serve


MCP_HOST = "localhost"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


MCP_PORT = _find_free_port()
MCP_URL = f"http://{MCP_HOST}:{MCP_PORT}/sse"


def _find_local_epw() -> Path | None:
    candidates = [
        Path("examples/openstudio_ai/resource/USA_FL_Tampa-MacDill.AFB.747880_TMY3.epw"),
        Path.home() / "github/openstudio-standards/data/weather/USA_FL_Tampa-MacDill.AFB.747880_TMY3.epw",
    ]
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.exists():
            return resolved
    return None


@pytest.fixture(scope="session", autouse=True)
def start_mcp():
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
            assert "model_load" in names
            assert "model_clone" in names
            assert "model_list_measures" in names
            assert "sim_run" in names

            result = await session.call_tool(
                name="model_load",
                arguments={"model_uri": "file:///tmp/dummy.osm"},
            )
            payload = result.structuredContent
            assert isinstance(payload, dict)
            assert payload["ok"] is True
            assert isinstance(payload["model_id"], str)


def test_openstudio_example_loads_yaml_a2a_server_with_mcp_config() -> None:
    mcp_config = build_openstudio_mcp_config()
    spec = load_openstudio_agent_spec(mcp_config)
    server = load_a2a_server_from_yaml(spec)
    factory_kwargs = spec.to_factory_kwargs()

    assert spec.agent_card["name"] == "OpenStudio AI Model Workspace Agent"
    assert spec.instructions.path == "../prompts/openstudio_agent.md"
    assert spec.mcp is not None
    assert "openstudio_mcp" in spec.mcp.servers
    assert spec.mcp.servers["openstudio_mcp"].host == mcp_config.host
    assert spec.mcp.servers["openstudio_mcp"].port == mcp_config.port
    assert factory_kwargs["tools_config"]["tools"][0]["type"] == "run_python"
    workspace_root = factory_kwargs["tools_config"]["tools"][0]["config"][
        "workspace_root"
    ]
    assert Path(workspace_root).resolve() == Path(
        "examples/openstudio_ai"
    ).resolve()
    assert factory_kwargs["skills_config"]["enabled"] is True
    assert "hvac_sizing_assistant" in factory_kwargs["skills_config"]["registry"]
    assert (
        "openstudio_sdk_model_editor"
        in factory_kwargs["skills_config"]["registry"]
    )
    assert "openstudio_sdk_wiki" in factory_kwargs["skills_config"]["registry"]
    skill_manager = SkillManager.from_config(factory_kwargs["skills_config"])
    available_context = set(skill_manager.available_skills())
    assert "sdk_index" in available_context
    assert "sdk_core_patterns" in available_context
    assert "sdk_geometry" in available_context
    assert "Purpose Routing" in skill_manager.load("sdk_index")
    model_editor_skill = skill_manager.load("openstudio_sdk_model_editor")
    assert "load `sdk_index`" in model_editor_skill
    assert "SDK Context-Pack Selection" in model_editor_skill
    assert "surface_azimuth_degrees(surface)" in model_editor_skill
    assert "Load `sdk_geometry` for geometry" in model_editor_skill
    instructions = spec.resolve_instructions()
    assert "### MCP `model_*`" in instructions
    assert "### MCP `sim_*`" in instructions
    assert "### MCP `results_*`" in instructions
    assert "load `openstudio_sdk_model_editor`" in instructions
    assert "use this loop" in instructions
    assert "hvac_sizing_assistant" in instructions
    assert "openstudio_sdk_model_editor" in instructions
    assert "sdk_index" not in instructions
    assert "surface_azimuth_degrees" not in instructions
    assert "fails three times" not in instructions
    assert "## Python Script Safeguard" not in instructions
    assert "Follow the skill instructions exactly" not in instructions
    assert isinstance(server, A2AAgentServer)
    assert server.name == "OpenStudio AI Model Workspace Agent"


def test_openstudio_ai_blackboard_config_supports_workflow_state(tmp_path: Path) -> None:
    spec = load_openstudio_agent_spec(build_openstudio_mcp_config())
    factory_kwargs = spec.to_factory_kwargs()
    blackboard_config = deepcopy(factory_kwargs["blackboard_config"])

    assert blackboard_config["enabled"] is True
    assert blackboard_config["store"]["backend"] == "local_json"
    assert Path(blackboard_config["store"]["base_dir"]).resolve() == Path(
        "examples/openstudio_ai/.openstudio_ai_blackboards"
    ).resolve()
    assert blackboard_config["schema_name"] == "openstudio_ai_workflow"
    assert blackboard_config["initial_data"] == {
        "active_workflow_id": None,
        "workflows": {},
        "operation_log": [],
        "handoff_notes": [],
    }
    assert (
        blackboard_config["schema"]["properties"]["workflows"][
            "additionalProperties"
        ]
        is True
    )
    assert (
        blackboard_config["schema"]["properties"]["operation_log"]["items"][
            "additionalProperties"
        ]
        is True
    )

    blackboard_config["store"]["base_dir"] = str(tmp_path)
    BlackboardSchemaRegistry.register(
        name=blackboard_config["schema_name"],
        version=blackboard_config["schema_version"],
        json_schema=blackboard_config["schema"],
        description=blackboard_config["schema_description"],
    )
    store = create_blackboard_store(blackboard_config["store"])
    doc = store.create(
        "session-1",
        blackboard_config["schema_name"],
        blackboard_config["schema_version"],
        blackboard_config["initial_data"],
    )

    workflow_id = "vav_reheat_001"
    workflow_state = {
        "workflow_id": workflow_id,
        "mode": "preflight",
        "input_model_path": None,
        "current_model_path": None,
        "output_model_path": None,
        "system": {"system_name": "3 Zone VAV", "target_zone_names": []},
        "schedules": {},
        "completed_steps": [],
        "pending_steps": ["preflight_inspection", "clarification_gate"],
        "created_objects": {},
        "assumptions": [],
        "warnings": [],
        "validation_results": [],
    }
    doc = store.apply_patch(
        "session-1",
        BlackboardPatch(
            ops=[
                {"op": "set", "path": "active_workflow_id", "value": workflow_id},
                {
                    "op": "set",
                    "path": f"workflows.{workflow_id}",
                    "value": workflow_state,
                },
                {
                    "op": "append",
                    "path": "operation_log",
                    "value": {
                        "operation": "initialize_workflow",
                        "workflow_id": workflow_id,
                        "phase": "preflight_inspection",
                        "note": "Initialized VAV workflow state.",
                    },
                },
            ],
            actor="openstudio_vav_reheat_system_creator",
            note="initialize_workflow",
        ),
        expected_revision=doc.revision,
    )

    doc = store.apply_patch(
        "session-1",
        BlackboardPatch(
            ops=[
                {
                    "op": "set",
                    "path": f"workflows.{workflow_id}.completed_steps",
                    "value": ["preflight_inspection"],
                },
                {
                    "op": "set",
                    "path": f"workflows.{workflow_id}.pending_steps",
                    "value": ["clarification_gate"],
                },
                {
                    "op": "append",
                    "path": "operation_log",
                    "value": {
                        "operation": "mark_step_complete",
                        "workflow_id": workflow_id,
                        "phase": "preflight_inspection",
                        "note": "Marked preflight complete.",
                    },
                },
            ],
            actor="openstudio_vav_reheat_system_creator",
            note="mark_step_complete",
        ),
        expected_revision=doc.revision,
    )

    loaded = store.load("session-1")
    assert loaded.data["active_workflow_id"] == workflow_id
    assert loaded.data["workflows"][workflow_id]["completed_steps"] == [
        "preflight_inspection"
    ]
    assert loaded.data["workflows"][workflow_id]["pending_steps"] == [
        "clarification_gate"
    ]
    assert [item["operation"] for item in loaded.data["operation_log"]] == [
        "initialize_workflow",
        "mark_step_complete",
    ]


@pytest.mark.asyncio
async def test_openstudio_mcp_apply_add_daylighting_measure() -> None:
    env_path = Path("examples/openstudio_ai/.env")
    env_values = dotenv_values(env_path) if env_path.exists() else {}
    openstudio_path = (
        os.getenv("OPENSTUDIO_PATH", "").strip()
        or str(env_values.get("OPENSTUDIO_PATH", "")).strip()
    )
    if not openstudio_path or not Path(openstudio_path).exists():
        pytest.skip("OPENSTUDIO_PATH is not configured to a valid executable.")

    sample_model_uri = (
        Path("examples/openstudio_ai/resource/sample.osm")
        .resolve()
        .as_uri()
    )
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            load_result = await session.call_tool(
                name="model_load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            original_model_id = load_payload["model_id"]

            measures_result = await session.call_tool(
                name="model_list_measures",
                arguments={},
            )
            measures_payload = measures_result.structuredContent
            assert isinstance(measures_payload, dict)
            assert measures_payload["ok"] is True
            measures = measures_payload.get("measures", [])
            assert any(item.get("measure_id") == "add_daylighting" for item in measures)

            apply_result = await session.call_tool(
                name="model_apply_measure",
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
                name="model_validate",
                arguments={"model_id": apply_payload["model_id"]},
            )
            validate_payload = validate_result.structuredContent
            assert isinstance(validate_payload, dict)
            assert validate_payload["ok"] is True


@pytest.mark.asyncio
async def test_openstudio_mcp_simulation_flow_with_sample_model() -> None:
    sample_model_uri = (
        Path("examples/openstudio_ai/resource/sample.osm")
        .resolve()
        .as_uri()
    )
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            load_result = await session.call_tool(
                name="model_load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            model_id = load_payload["model_id"]

            run_result = await session.call_tool(
                name="sim_run",
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
                    name="sim_status",
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
    env_path = Path("examples/openstudio_ai/.env")
    env_values = dotenv_values(env_path) if env_path.exists() else {}
    openstudio_path = (
        os.getenv("OPENSTUDIO_PATH", "").strip()
        or str(env_values.get("OPENSTUDIO_PATH", "")).strip()
    )
    if not openstudio_path or not Path(openstudio_path).exists():
        pytest.skip("OPENSTUDIO_PATH is not configured to a valid executable.")
    epw_path = _find_local_epw()
    if epw_path is None:
        pytest.skip("Local EPW file not found for real simulation test.")

    sample_model_uri = (
        Path("examples/openstudio_ai/resource/sample.osm")
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
                name="model_load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            model_id = load_payload["model_id"]

            set_weather_result = await session.call_tool(
                name="model_set_weather",
                arguments={"model_id": model_id, "epw_path": str(epw_path)},
            )
            set_weather_payload = set_weather_result.structuredContent
            assert isinstance(set_weather_payload, dict)
            assert set_weather_payload["ok"] is True

            run_result = await session.call_tool(
                name="sim_run",
                arguments={"model_id": model_id, "run_mode": "sizing", "options": {}},
            )
            run_payload = run_result.structuredContent
            assert isinstance(run_payload, dict)
            assert run_payload["ok"] is True
            job_id = run_payload["job_id"]

            final_state = None
            for _ in range(360):
                status_result = await session.call_tool(
                    name="sim_status",
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
                name="sim_artifacts",
                arguments={"job_id": job_id},
            )
            artifacts_payload = artifacts_result.structuredContent
            assert isinstance(artifacts_payload, dict)
            assert artifacts_payload["ok"] is True
            assert isinstance(artifacts_payload["sql_id"], str)
            assert isinstance(artifacts_payload["logs_id"], str)

            query_result = await session.call_tool(
                name="results_query",
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
