import asyncio
import uuid
from typing import Literal

import pytest
from a2a.types import (
    Role,
    TaskState,
    Message,
    MessageSendParams,
    Part,
    TextPart,
)
from a2a.server.events import EventQueue
from a2a.server.agent_execution import RequestContext
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from automa_ai.agents.react_langgraph_agent import GenericLangGraphReactAgent
from automa_ai.common import prompts
from automa_ai.common.types import TaskList
from automa_ai.common.agent_executor import GenericAgentExecutor


class ResponseFormat(BaseModel):
    status: Literal["input_required", "completed", "error"] = "input_required"
    question: str = Field(description="Input needed from the user to generate the plan")
    content: TaskList = Field(description="List of tasks when the plan is generated")


async def interactive_loop(agent_executor, context_id, task_id):
    while True:
        user_input = input("👤 Your reply: ")
        if not user_input:
            print("❌ Ending interaction.")
            break

        message_id = str(uuid.uuid4().hex)
        user_message = Message(
            role=Role.user,
            parts=[Part(root=TextPart(text=str(user_input)))],
            context_id=context_id,
            message_id=message_id,
        )

        message = MessageSendParams(message=user_message)

        context = RequestContext(
            request=message,
            context_id=context_id,
            task_id=task_id,
            task=None,
        )

        event_queue = EventQueue()
        await agent_executor.execute(context, event_queue)

        # Process events and check for completion
        task_completed = False
        final_result = None

        while True:
            try:
                # set timeout to 8 seconds
                event = await asyncio.wait_for(event_queue.dequeue_event(), timeout=10)
                print(f"📤 {event}")

                # Check if this is a completion event
                if hasattr(event, "status") and event.status:
                    if event.status.state == TaskState.completed:
                        print("Task completed!----")
                        task_completed = True
                        # Extract the final result from the message
                        if event.status.message and event.status.message.parts:
                            for part in event.status.message.parts:
                                if hasattr(part.root, "text"):
                                    final_result = part.root.text
                                    print(final_result)
                                elif hasattr(part.root, "data"):
                                    final_result = part.root.data
                                    print(final_result)
                        break
                    elif event.status.state == TaskState.input_required:
                        print("Task input required !----")

                        # Continue the loop to ask for more input
                        break
                    elif event.status.state == TaskState.working:
                        print("Task working!!! !----")

                        # Check if the working message contains completion status
                        if event.status.message and event.status.message.parts:
                            for part in event.status.message.parts:
                                if hasattr(part.root, "text"):
                                    text = part.root.text
                                    # Check if this contains a completion status
                                    if '"status": "completed"' in text:
                                        task_completed = True
                                        final_result = text
                                        break
                        if task_completed:
                            break

            except asyncio.TimeoutError as e:
                print(e)
                break

        # If task is completed, show final result and exit
        if task_completed:
            print("\n🎉 Task completed!")
            if final_result:
                print(f"📋 Final Result:\n{final_result}")
            break


@pytest.mark.asyncio
async def executor():
    # Initial user message
    latest_message_id = "test-message"
    user_message = Message(
        role=Role.user,
        parts=[
            Part(
                root=TextPart(text="Create an energy model task list for a new school")
            )
        ],
        context_id="test-context-id",
        message_id=latest_message_id,
    )

    message = MessageSendParams(message=user_message)

    # Generate initial context/task IDs
    context_id = "test-context-id"
    task_id = str(uuid.uuid4())

    # Initial RequestContext
    context = RequestContext(
        request=message,
        context_id=context_id,
        task_id=task_id,
        task=None,
        related_tasks=None,
        call_context=None,
    )

    # Create agent and executor
    agent = GenericLangGraphReactAgent(
        agent_name="PlannerAgent",
        description="Helps breakdown a building energy modeling request into actionable tasks",
        instructions=prompts.PLANNER_COT_INSTRUCTIONS,
        response_format=ResponseFormat,
        chat_model=ChatOllama(model="llama3.1:8b", temperature=0),
    )
    executor = GenericAgentExecutor(agent)

    # Initial execution
    event_queue = EventQueue()
    await executor.execute(context, event_queue)

    # Drain queue safely using timeout
    while True:
        try:
            event = await asyncio.wait_for(event_queue.dequeue_event(), timeout=10)
            print(f"📤 {event}")
        except asyncio.TimeoutError:
            break

    # Now enter interactive loop
    await interactive_loop(executor, context_id, task_id)


if __name__ == "__main__":
    asyncio.run(executor())
