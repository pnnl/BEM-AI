import uuid
from typing import AsyncGenerator

from google.adk import Agent, Runner
from google.adk.events import Event
from google.adk.sessions import InMemorySessionService
from google.genai import types


class AgentRunner:
    """
    Manages the execution of an ADK (Agent Development Kit) Agent.
    This class encapsulates the logic for running an agent, handling session management (creation and retrieval)
    and streaming response back to the caller, It uses an in-memory session service.
    Handles how an agent launched and communicated with. - Deployment code.
    """

    def __init__(self, user_id: str = "user", app_name: str = "BEM-A2A"):
        self.session_service = InMemorySessionService()
        self.session = None
        self.app_name = app_name
        self.user_id = user_id

    async def run_stream(
        self, agent: Agent, query: str, session_id: str
    ) -> AsyncGenerator[Event, None]:
        runner = Runner(
            agent=agent, app_name=self.app_name, session_service=self.session_service
        )

        if not session_id:
            session_id = uuid.uuid4().hex
        else:
            self.session = await self.session_service.get_session(
                app_name=self.app_name, user_id=self.user_id, session_id=session_id
            )

        if not self.session:
            self.session = await self.session_service.create_session(
                app_name=self.app_name, user_id=self.user_id, session_id=session_id
            )

        content = types.Content(role="user", parts=[types.Part(text=query)])

        async for event in runner.run_async(
            user_id=self.user_id, session_id=self.session.id, new_message=content
        ):
            if event.is_final_response():
                response = ""
                if (
                    event.content
                    and event.content.parts
                    and event.content.parts[0].text
                ):
                    # Message
                    response = "\n".join(
                        [p.text for p in event.content.parts if p.text]
                    )
                elif (
                    event.content
                    and event.content.parts
                    and any(True for p in event.content.parts if p.function_response)
                ):
                    # Tool call response
                    response = next(
                        p.function_response.model_dump() for p in event.content.parts
                    )
                else:
                    response = f"Error in running agent: {agent.name}"
                yield {"type": "final_result", "response": response}
            else:
                yield {
                    "is_task_complete": False,
                    "require_user_input": False,
                    "content": f"{agent.name}: Processing requires...",
                }
