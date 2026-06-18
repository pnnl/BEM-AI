from __future__ import annotations

import json

import pytest

from automa_ai.config.tools import ToolSpec
from automa_ai.tools import build_langchain_tools
from automa_ai.tools.run_python.config import RunPythonToolConfig
from automa_ai.tools.run_python.tool import RunPythonTool


def test_registry_build_includes_run_python_and_web_search() -> None:
    tools = build_langchain_tools(
        [
            ToolSpec(type="web_search", config={"provider": "opensource"}),
            ToolSpec(type="run_python", config={}),
        ]
    )
    names = {tool.name for tool in tools}
    assert "web_search" in names
    assert "run_python" in names


def test_run_python_tool_guides_workspace_relative_inputs() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    schema = tool.args_schema.model_json_schema()

    assert "workspace-relative paths in input_files" in tool.description
    assert "Do not use absolute /Users/... paths" in tool.description
    assert "Workspace-relative file paths" in schema["properties"]["input_files"][
        "description"
    ]
    assert "Do not pass absolute local paths" in schema["properties"]["input_files"][
        "description"
    ]


@pytest.mark.asyncio
async def test_run_python_happy_path_arithmetic() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke({"code": "print(sum(i*i for i in range(6)))"})

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "55"
    assert result["meta"]["script"]["line_count"] == 1
    assert result["meta"]["script"]["char_count"] == len(
        "print(sum(i*i for i in range(6)))"
    )


@pytest.mark.asyncio
async def test_run_python_records_failure_experience(tmp_path) -> None:
    log_path = tmp_path / "python_script_failure_experience.jsonl"
    tool = RunPythonTool(
        RunPythonToolConfig.model_validate(
            {
                "workspace_root": str(tmp_path),
                "failure_experience_path": str(log_path),
            }
        )
    )

    result = await tool.invoke({"code": "raise RuntimeError('bad sdk call')"})

    assert result["success"] is False
    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["stage"] == "runtime"
    assert records[0]["script"]["code"] == "raise RuntimeError('bad sdk call')"
    assert "bad sdk call" in records[0]["stderr"]


@pytest.mark.asyncio
async def test_run_python_warns_for_long_script(tmp_path) -> None:
    tool = RunPythonTool(
        RunPythonToolConfig.model_validate(
            {"workspace_root": str(tmp_path), "warn_script_lines": 2}
        )
    )

    result = await tool.invoke({"code": "x = 1\ny = 2\nprint(x + y)"})

    assert result["success"] is True
    assert result["meta"]["script"]["line_count"] == 3
    assert any("Script is long" in w for w in result["meta"]["warnings"])


@pytest.mark.asyncio
async def test_run_python_blocks_configured_script_length_limit(tmp_path) -> None:
    log_path = tmp_path / "python_script_failure_experience.jsonl"
    tool = RunPythonTool(
        RunPythonToolConfig.model_validate(
            {
                "workspace_root": str(tmp_path),
                "max_script_lines": 2,
                "failure_experience_path": str(log_path),
            }
        )
    )

    result = await tool.invoke({"code": "x = 1\ny = 2\nprint(x + y)"})

    assert result["success"] is False
    assert "max_script_lines" in result["stderr"]
    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["stage"] == "script_length_limit"


@pytest.mark.asyncio
async def test_run_python_parses_json_and_csv(tmp_path) -> None:
    json_path = tmp_path / "input.json"
    csv_path = tmp_path / "input.csv"
    json_path.write_text(json.dumps({"name": "demo", "value": 7}), encoding="utf-8")
    csv_path.write_text("city,temp\nA,23\nB,19\n", encoding="utf-8")

    tool = RunPythonTool(
        RunPythonToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    code = """
import csv
import json

with open('input.json', 'r', encoding='utf-8') as f:
    payload = json.load(f)

with open('input.csv', 'r', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

print(payload['name'], payload['value'], len(rows))
"""
    result = await tool.invoke(
        {
            "code": code,
            "input_files": ["input.json", "input.csv"],
        }
    )

    assert result["success"] is True
    assert result["stdout"].strip() == "demo 7 2"


@pytest.mark.asyncio
async def test_run_python_collects_artifact(tmp_path) -> None:
    tool = RunPythonTool(
        RunPythonToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    code = """
with open('table.csv', 'w', encoding='utf-8') as f:
    f.write('x,y\\n1,2\\n3,4\\n')
print('done')
"""
    result = await tool.invoke(
        {
            "code": code,
            "expected_outputs": ["table.csv"],
        }
    )

    assert result["success"] is True
    assert result["artifacts"]
    assert result["artifacts"][0]["path"] == "table.csv"


@pytest.mark.asyncio
async def test_run_python_policy_rejects_disallowed_import() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke({"code": "import subprocess\nprint('x')"})

    assert result["success"] is False
    assert "Blocked import" in result["stderr"]
    assert "sandbox policy" in result["meta"]["warnings"][0].lower()


@pytest.mark.asyncio
async def test_run_python_allows_os_for_local_path_handling(tmp_path) -> None:
    input_path = tmp_path / "nested" / "input.txt"
    input_path.parent.mkdir()
    input_path.write_text("ok", encoding="utf-8")

    tool = RunPythonTool(
        RunPythonToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke(
        {
            "code": "import os\nprint(os.path.exists(os.path.join('nested', 'input.txt')))",
            "input_files": ["nested/input.txt"],
        }
    )

    assert result["success"] is True
    assert result["stdout"].strip() == "True"


@pytest.mark.asyncio
async def test_run_python_allows_pathlib_for_local_path_handling(tmp_path) -> None:
    input_path = tmp_path / "nested" / "input.txt"
    input_path.parent.mkdir()
    input_path.write_text("ok", encoding="utf-8")

    tool = RunPythonTool(
        RunPythonToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke(
        {
            "code": (
                "from pathlib import Path\n"
                "print((Path('nested') / 'input.txt').read_text(encoding='utf-8'))"
            ),
            "input_files": ["nested/input.txt"],
        }
    )

    assert result["success"] is True
    assert result["stdout"].strip() == "ok"


@pytest.mark.asyncio
async def test_run_python_still_rejects_os_system() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke({"code": "import os\nos.system('echo unsafe')"})

    assert result["success"] is False
    assert "Blocked call pattern" in result["stderr"]


@pytest.mark.asyncio
async def test_run_python_rejects_os_spawn_process_launch() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke(
        {"code": "import os\nos.spawnv(os.P_NOWAIT, '/bin/echo', ['echo', 'unsafe'])"}
    )

    assert result["success"] is False
    assert "Blocked call pattern" in result["stderr"]


@pytest.mark.asyncio
async def test_run_python_rejects_os_exec_process_launch() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke({"code": "import os\nos.execv('/bin/echo', ['echo'])"})

    assert result["success"] is False
    assert "Blocked call pattern" in result["stderr"]


@pytest.mark.asyncio
async def test_run_python_allows_urllib_parse_only() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke(
        {
            "code": (
                "from urllib.parse import urlparse\n"
                "print(urlparse('https://example.com/a').path)"
            )
        }
    )

    assert result["success"] is True
    assert result["stdout"].strip() == "/a"


@pytest.mark.asyncio
async def test_run_python_still_rejects_urllib_request() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke({"code": "import urllib.request\nprint('x')"})

    assert result["success"] is False
    assert "Blocked import: urllib" in result["stderr"]


@pytest.mark.asyncio
async def test_run_python_still_rejects_network_imports() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke({"code": "import socket\nprint('x')"})

    assert result["success"] is False
    assert "Blocked import: socket" in result["stderr"]


@pytest.mark.asyncio
async def test_run_python_does_not_return_copied_inputs_as_artifacts(tmp_path) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("seed", encoding="utf-8")

    tool = RunPythonTool(
        RunPythonToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke(
        {
            "code": "print(open('input.txt', encoding='utf-8').read())",
            "input_files": ["input.txt"],
        }
    )

    assert result["success"] is True
    assert result["artifacts"] == []


@pytest.mark.asyncio
async def test_run_python_disables_artifact_collection_when_max_artifacts_zero(
    tmp_path,
) -> None:
    tool = RunPythonTool(
        RunPythonToolConfig.model_validate(
            {"workspace_root": str(tmp_path), "max_artifacts": 0}
        )
    )
    result = await tool.invoke(
        {
            "code": "open('result.txt', 'w', encoding='utf-8').write('ok')",
        }
    )

    assert result["success"] is True
    assert result["artifacts"] == []
    assert all("Artifact limit reached" not in w for w in result["meta"]["warnings"])


@pytest.mark.asyncio
async def test_run_python_returns_only_generated_outputs_without_expected(
    tmp_path,
) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("seed", encoding="utf-8")

    tool = RunPythonTool(
        RunPythonToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke(
        {
            "code": "open('output.txt', 'w', encoding='utf-8').write('ok')",
            "input_files": ["input.txt"],
        }
    )

    assert result["success"] is True
    assert [a["path"] for a in result["artifacts"]] == ["output.txt"]


@pytest.mark.asyncio
async def test_run_python_rejects_getattr_import_bypass() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke(
        {"code": "getattr(__builtins__, '__import__')('os').system('echo unsafe')"}
    )

    assert result["success"] is False
    assert "Blocked" in result["stderr"]


@pytest.mark.asyncio
async def test_run_python_invalid_input_file_returns_structured_error(tmp_path) -> None:
    tool = RunPythonTool(
        RunPythonToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke(
        {
            "code": "print('x')",
            "input_files": ["../outside.txt"],
        }
    )

    assert result["success"] is False
    assert result["exit_code"] == 1
    assert "workspace_root" in result["stderr"]
    assert "before Python process start" in result["meta"]["warnings"][0]


@pytest.mark.asyncio
async def test_run_python_rejects_reserved_startup_filename(tmp_path) -> None:
    reserved = tmp_path / "sitecustomize.py"
    reserved.write_text("print('bad')", encoding="utf-8")

    tool = RunPythonTool(
        RunPythonToolConfig.model_validate({"workspace_root": str(tmp_path)})
    )
    result = await tool.invoke(
        {
            "code": "print('ok')",
            "input_files": ["sitecustomize.py"],
        }
    )

    assert result["success"] is False
    assert "Reserved input filename" in result["stderr"]
