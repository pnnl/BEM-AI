from __future__ import annotations

import json

import pytest

from automa_ai.config.tools import ToolSpec
from automa_ai.tools.registry import build_langchain_tools
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


@pytest.mark.asyncio
async def test_run_python_happy_path_arithmetic() -> None:
    tool = RunPythonTool(RunPythonToolConfig.model_validate({}))
    result = await tool.invoke({"code": "print(sum(i*i for i in range(6)))"})

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "55"


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
