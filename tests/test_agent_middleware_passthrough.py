"""Tests for caller-supplied LangChain middleware reaching ``create_agent``."""

import pickle

import pytest
from langchain.agents.middleware import AgentMiddleware

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.agents import langgraph_chatagent


def _card():
    return {
        "name": "middleware-agent",
        "description": "Agent for middleware passthrough tests.",
        "supportedInterfaces": [
            {
                "url": "http://localhost:34567",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
    }


class _TestMiddleware(AgentMiddleware):
    """Stand-in for a real middleware; identity is all the tests check."""


def _build_agent(monkeypatch, middleware):
    monkeypatch.setattr(
        "automa_ai.agents.agent_factory.resolve_chat_model",
        lambda *args, **kwargs: None,
    )
    return AgentFactory(
        card=_card(),
        instructions="test",
        model_name="dummy",
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.OLLAMA,
        middleware=middleware,
    ).get_agent()


def test_factory_passes_middleware_to_chat_agent(monkeypatch):
    marker = _TestMiddleware()
    agent = _build_agent(monkeypatch, [marker])
    assert agent.middleware == [marker]


def test_middleware_defaults_to_empty_list(monkeypatch):
    agent = _build_agent(monkeypatch, None)
    assert agent.middleware == []


def test_caller_list_mutation_does_not_affect_agent(monkeypatch):
    supplied = [_TestMiddleware()]
    agent = _build_agent(monkeypatch, supplied)
    supplied.append(_TestMiddleware())
    assert len(agent.middleware) == 1


def test_caller_list_mutation_before_get_agent_does_not_affect_agent(monkeypatch):
    """The factory snapshots at construction, so this window is closed too."""
    monkeypatch.setattr(
        "automa_ai.agents.agent_factory.resolve_chat_model",
        lambda *args, **kwargs: None,
    )
    supplied = [_TestMiddleware()]
    factory = AgentFactory(
        card=_card(),
        instructions="test",
        model_name="dummy",
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.OLLAMA,
        middleware=supplied,
    )
    supplied.append(_TestMiddleware())
    assert len(factory.get_agent().middleware) == 1


@pytest.mark.asyncio
async def test_middleware_appended_after_budget_stack(monkeypatch):
    """Caller middleware must land last so it sits closest to the model call."""
    marker = _TestMiddleware()
    agent = _build_agent(monkeypatch, [marker])

    captured = {}

    def fake_create_agent(model, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(langgraph_chatagent, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        langgraph_chatagent,
        "build_token_budget_middlewares",
        lambda **kwargs: ["budget-stub"],
    )

    async def emitter(_event):
        return None

    await agent.init_graph(emitter)

    assert captured["middleware"] == ["budget-stub", marker]


def test_config_only_middleware_survives_pickling():
    """Factory kwargs get pickled for `spawn`, so middleware must round-trip."""
    factory = AgentFactory(
        card=_card(),
        instructions="test",
        model_name="dummy",
        agent_type=GenericAgentType.LANGGRAPHCHAT,
        chat_model=GenericLLM.OLLAMA,
        middleware=[_TestMiddleware()],
    )
    restored = pickle.loads(pickle.dumps(factory))
    assert isinstance(restored.middleware[0], _TestMiddleware)
