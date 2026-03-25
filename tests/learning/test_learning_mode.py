from __future__ import annotations

import asyncio

import pytest

from automa_ai.agents.langgraph_chatagent import GenericLangGraphChatAgent
from automa_ai.config.learning import LearningWorkflowConfig


@pytest.mark.asyncio
async def test_learning_mode_disabled_no_background_workflow(monkeypatch):
    called = False

    async def fake_run_learning_workflow(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "automa_ai.agents.langgraph_chatagent.run_learning_workflow",
        fake_run_learning_workflow,
    )

    agent = GenericLangGraphChatAgent(
        agent_name="test",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        learning_config=LearningWorkflowConfig(enabled=False),
    )

    await agent._trigger_learning_workflow(
        query="q",
        final_response="ok",
        response_type="text",
        session_id="s1",
        task_id="t1",
    )

    assert called is False


@pytest.mark.asyncio
async def test_learning_mode_enabled_schedules_background_workflow(monkeypatch):
    started = asyncio.Event()
    finished = asyncio.Event()

    async def fake_run_learning_workflow(**kwargs):
        started.set()
        await asyncio.sleep(0.05)
        finished.set()

    monkeypatch.setattr(
        "automa_ai.agents.langgraph_chatagent.run_learning_workflow",
        fake_run_learning_workflow,
    )

    agent = GenericLangGraphChatAgent(
        agent_name="test",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        learning_config=LearningWorkflowConfig(enabled=True),
    )

    await agent._trigger_learning_workflow(
        query="q",
        final_response="ok",
        response_type="text",
        session_id="s2",
        task_id="t2",
    )

    assert started.is_set()
    assert finished.is_set() is False
    await asyncio.wait_for(finished.wait(), timeout=1)


@pytest.mark.asyncio
async def test_learning_background_failure_does_not_raise(monkeypatch):
    async def fake_run_learning_workflow(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "automa_ai.agents.langgraph_chatagent.run_learning_workflow",
        fake_run_learning_workflow,
    )

    agent = GenericLangGraphChatAgent(
        agent_name="test",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        learning_config=LearningWorkflowConfig(enabled=True),
    )

    await agent._trigger_learning_workflow(
        query="q",
        final_response="ok",
        response_type="text",
        session_id="s3",
        task_id="t3",
    )
    await asyncio.sleep(0.05)
