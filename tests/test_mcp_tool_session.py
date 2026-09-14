import sys
import types

import pytest

from automa_ai.common import utils


@pytest.mark.asyncio
async def test_mcp_tools_keep_adapters_open_until_session_close(monkeypatch) -> None:
    adapters = []

    class FakeAdapter:
        def __init__(self, target) -> None:
            self.target = target
            self.exited = False
            adapters.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            self.exited = True

        async def list_tools(self):
            return [self.target]

    monkeypatch.setattr(utils, "_mcp_adapter_targets", lambda _: ["one", "two"])
    monkeypatch.setitem(sys.modules, "langchain.mcp", types.SimpleNamespace(MCPAdapter=FakeAdapter))

    tools = await utils.load_mcp_tools({})

    assert list(tools) == ["one", "two"]
    assert [adapter.exited for adapter in adapters] == [False, False]

    await tools.aclose()

    assert [adapter.exited for adapter in adapters] == [True, True]
