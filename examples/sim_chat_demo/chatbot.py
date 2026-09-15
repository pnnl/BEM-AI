from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from automa_ai.config.agent_spec import YamlAgentSpec, load_agent_factory_from_yaml
from automa_ai.memory.chroma_memory_store import ChromaVectorMemoryStore
from automa_ai.memory.manager import MemoryStoreRegistry
from automa_ai.memory.sqlite_memory_store import SQLiteMemoryStore


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
SPEC_PATH = BASE_DIR / "agent.yaml"


def _register_memory_stores() -> None:
    for name, store in {
        "default_sqlite": SQLiteMemoryStore,
        "default_chroma": ChromaVectorMemoryStore,
    }.items():
        try:
            MemoryStoreRegistry.register(name, store)
        except ValueError:
            pass


def build_chatbot():
    """Build the standalone YAML agent without starting an A2A or MCP server."""
    _register_memory_stores()
    spec = YamlAgentSpec.from_yaml_file(SPEC_PATH)
    spec.model.name = os.getenv("CHAT_BOT_MODEL_NAME", spec.model.name)
    spec.model.base_url = os.getenv("CHAT_BOT_MODEL_BASE_URL") or None
    return load_agent_factory_from_yaml(spec).get_agent()
