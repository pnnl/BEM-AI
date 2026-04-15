"""Run a simple run_python tool call from YAML/dict config."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from automa_ai.config.tools import ToolsConfig
from automa_ai.tools import build_langchain_tools


def _load_config(path: str | None) -> dict:
    if path is None:
        return {
            "tools": [
                {
                    "type": "run_python",
                    "config": {
                        "runner": "local_subprocess",
                        "timeout_s": 20,
                    },
                }
            ]
        }

    p = Path(path)
    text = p.read_text()
    if p.suffix in {".yaml", ".yml"}:
        import yaml  # optional

        return yaml.safe_load(text)
    return json.loads(text)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--code",
        type=str,
        default="print(sum(i * i for i in range(10)))",
        help="Python code to execute.",
    )
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    config = ToolsConfig.from_dict(_load_config(args.config))
    tools = build_langchain_tools(config.tools)
    run_python = next((t for t in tools if t.name == "run_python"), None)
    if run_python is None:
        raise ValueError(
            "No tool named 'run_python' was found. "
            "Please ensure your tools configuration includes a 'run_python' tool."
        )
    out = await run_python.ainvoke({"code": args.code})
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
