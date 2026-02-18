"""Run a simple web_search tool call from YAML/dict config."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from automa_ai.config.tools import ToolsConfig
from automa_ai.tools import build_langchain_tools


def _load_config(path: str | None) -> dict:
    if path is None:
        return {
            "tools": [
                {
                    "type": "web_search",
                    "config": {
                        "provider": "auto",
                        "serper": {"api_key": os.getenv("SERPER_API_KEY")},
                        "firecrawl": {
                            "api_key": os.getenv("FIRECRAWL_API_KEY"),
                            "enabled": True,
                        },
                        "rerank": {"provider": "opensource", "top_k": 5},
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
    parser.add_argument("query", type=str)
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    config = ToolsConfig.from_dict(_load_config(args.config))
    tools = build_langchain_tools(config.tools)
    web_search = next((t for t in tools if t.name == "web_search"), None)
    if web_search is None:
        raise ValueError(
            "No tool named 'web_search' was found. "
            "Please ensure your tools configuration includes a 'web_search' tool."
        )
    out = await web_search.ainvoke({"query": args.query})
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
