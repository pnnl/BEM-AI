import asyncio
import uuid
from typing import Literal

import pytest

from google.protobuf.json_format import MessageToDict

from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from automa_ai.agents.react_langgraph_agent import GenericLangGraphReactAgent
from automa_ai.common import prompts
from automa_ai.common.agent_executor import GenericAgentExecutor
from automa_ai.common.types import TaskList


class ResponseFormat(BaseModel):
    status: Literal["input_required", "completed", "error"] = "input_required"
    question: str = Field(
        description="Input needed from the user to generate the plan"
    )
    content: TaskList = Field(
        description="List of tasks when the plan is generated"
    )


async def interactive_loop(agent_executor, context_id, task_id):
    while True:
        user_input = input("👤 Your reply: ")
        if not user_input:
            print("❌ Ending interaction.")
            break

        user_message = Message(
            role=Role.ROLE_USER,
            parts=[Part(text=str(user_input))],
            context_id=context_id,
            task_id=task_id,
            message_id=str(uuid.uuid4().hex),
        )

        context = RequestContext(
            call_context=ServerCallContext(),
            request=SendMessageRequest(message=user_message),
            context_id=context_id,
            task_id=task_id,
            task=None,
        )

        event_queue = EventQueue()
        await agent_executor.execute(context, event_queue)

        task_completed = False
        final_result = None

        while True:
            try:
                event = await asyncio.wait_for(
                    event_queue.dequeue_event(), timeout=10
                )
                print(f"📤 {event}")

                if hasattr(event, "status") and event.status:
                    if event.status.state == TaskState.TASK_STATE_COMPLETED:
                        print("Task completed!----")
                        task_completed = True
                        if event.status.message and event.status.message.parts:
                            for part in event.status.message.parts:
                                if part.HasField("text"):
                                    final_result = part.text
                                    print(final_result)
                                elif part.HasField("data"):
                                    final_result = MessageToDict(part.data)
                                    print(final_result)
                        break
                    elif (
                        event.status.state
                        == TaskState.TASK_STATE_INPUT_REQUIRED
                    ):
                        print("Task input required !----")
                        break
                    elif event.status.state == TaskState.TASK_STATE_WORKING:
                        print("Task working!!! !----")
                        if event.status.message and event.status.message.parts:
                            for part in event.status.message.parts:
                                if part.HasField("text"):
                                    text = part.text
                                    if '"status": "completed"' in text:
                                        task_completed = True
                                        final_result = text
                                        break
                        if task_completed:
                            break

            except asyncio.TimeoutError as e:
                print(e)
                break

        if task_completed:
            print("\n🎉 Task completed!")
            if final_result:
                print(f"📋 Final Result:\n{final_result}")
            break


@pytest.mark.asyncio
async def executor():
    task_id = str(uuid.uuid4())
    context_id = "test-context-id"

    user_message = Message(
        role=Role.ROLE_USER,
        parts=[Part(text="Create an energy model task list for a new school")],
        context_id=context_id,
        task_id=task_id,
        message_id="test-message",
    )

    context = RequestContext(
        call_context=ServerCallContext(),
        request=SendMessageRequest(message=user_message),
        context_id=context_id,
        task_id=task_id,
        task=None,
        related_tasks=None,
    )

    agent = GenericLangGraphReactAgent(
        agent_name="PlannerAgent",
        description=(
            "Helps breakdown a building energy modeling request into actionable tasks"
        ),
        instructions=prompts.PLANNER_COT_INSTRUCTIONS,
        response_format=ResponseFormat,
        chat_model=ChatOllama(model="llama3.1:8b", temperature=0),
    )
    executor = GenericAgentExecutor(agent)

    event_queue = EventQueue()
    await executor.execute(context, event_queue)

    while True:
        try:
            event = await asyncio.wait_for(
                event_queue.dequeue_event(), timeout=10
            )
            print(f"📤 {event}")
        except asyncio.TimeoutError:
            break

    await interactive_loop(executor, context_id, task_id)


if __name__ == "__main__":
    asyncio.run(executor())
