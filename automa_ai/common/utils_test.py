import pytest
from unittest import mock
from types import SimpleNamespace

from automa_ai.common.utils import load_memory_store_plugins, load_tool_plugins
from automa_ai.memory.manager import MemoryStoreRegistry
from automa_ai.memory.memory_stores import BaseMemoryStore
from automa_ai.tools.registry import DEFAULT_TOOL_REGISTRY
from automa_ai.tools.base import BaseDefaultTool, RuntimeDeps
from pydantic import BaseModel


# Dummy memory store for testing
class DummyMemoryStore(BaseMemoryStore):
    @classmethod
    def from_config(cls, config: dict):
        return cls()

    def write_memory(self, entries):
        return None

    def read_memories(self, query=None, session_id=None, user_id=None, memory_type=None, limit=10):
        return []

    def delete_memory(self, memory_id: str) -> bool:
        return True

    def clear_memories(self, memory_type=None) -> None:
        return None


class DummyArgs(BaseModel):
    query: str


class DummyTool(BaseDefaultTool):
    type = "dummy_tool"

    @property
    def args_schema(self):
        return DummyArgs

    @property
    def description(self):
        return "Dummy tool"

    async def invoke(self, payload):
        return {"ok": True}


def dummy_tool_builder(config: dict, deps: RuntimeDeps) -> BaseDefaultTool:
    return DummyTool()


def test_load_memory_store_plugins_registers_store(monkeypatch):
    fake_ep = SimpleNamespace(name="dummy_store", load=lambda: DummyMemoryStore)

    with mock.patch("importlib.metadata.entry_points") as mock_eps:
        mock_eps.return_value = {"automa_ai.memory_stores": [fake_ep]}

        MemoryStoreRegistry._stores.clear()

        load_memory_store_plugins()

        registered_cls = MemoryStoreRegistry.get("dummy_store")
        assert registered_cls is DummyMemoryStore


def test_load_tool_plugins_registers_tool_builder(monkeypatch):
    fake_ep = SimpleNamespace(name="dummy_tool", load=lambda: dummy_tool_builder)

    with mock.patch("importlib.metadata.entry_points") as mock_eps:
        mock_eps.return_value = {"automa_ai.tools": [fake_ep]}

        DEFAULT_TOOL_REGISTRY._builders.pop("dummy_tool", None)

        load_tool_plugins()

        assert "dummy_tool" in DEFAULT_TOOL_REGISTRY._builders
