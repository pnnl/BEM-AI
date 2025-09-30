import logging

from a2a.types import SendStreamingMessageSuccessResponse, TaskStatusUpdateEvent, TaskState, TaskArtifactUpdateEvent

from common.base_agent import BaseAgent
from network.agentic_network import ServiceOrchestrator

logger = logging.getLogger(__name__)

class ChatServiceOrchestrator(ServiceOrchestrator):
    def __init__(self, orchestrator_agent: BaseAgent, agent_cards_dir: str):
        """
        :param orchestrator_agent: An orchestrator layer to interact with all other AI agents and produce summary when task completed.
        :param agent_cards_dir: The directory to access agents
        """
        super().__init__(orchestrator=orchestrator_agent, agent_cards_dir=agent_cards_dir)

    async def user_query(self, query: str, context_id: str, task_id: str):
        try:
            results = []
            async for chunk in self.orchestrator.stream(
                query, context_id, task_id
            ):
                # ✅ STEP 1: Check if this is a wrapped streaming message
                if hasattr(chunk, "root") and isinstance(
                    chunk.root, SendStreamingMessageSuccessResponse
                ):
                    message_event = chunk.root.result
                    logger.info(message_event)
                    # ✅ STEP 2: Handle input required
                    if isinstance(message_event, TaskStatusUpdateEvent):
                        if message_event.status.state == TaskState.completed:
                            print("✅ Task completed.")
                            break
                    elif isinstance(message_event, TaskArtifactUpdateEvent):
                        results.append(message_event.artifact)
                        print("📦 Received artifact:", message_event.artifact)
                # ✅ STEP 3: Final summary message from orchestrator
                elif isinstance(chunk, dict):
                    results.append(chunk)
                    print("✅ Final summary:", chunk)
                    if chunk.get("is_task_complete"):
                        break
                else:
                    print(f"⚠️ Unexpected chunk type: {type(chunk)}")
                    print(chunk)
                    results.append(chunk)
        finally:
            print("🛑 Tearing down agentic network")
            await self.shutdown_all()




