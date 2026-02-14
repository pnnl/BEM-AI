import os

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    Task,
    UnsupportedOperationError,
    InvalidParamsError,
    SendStreamingMessageResponse,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    DataPart,
    TextPart,
    TaskState,
)
from a2a.utils import new_task, new_agent_text_message
from a2a.utils.errors import ServerError

from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.setup_logging import setup_file_logger


class GenericAgentExecutor(AgentExecutor):
    """Agent Executor used by modeling agents.
    Core business logic on how agent handles tasks, formats responses, process streaming and cancellation.
    This defines agent behavior and interface with the A2A runtime
    """

    def __init__(self, agent: BaseAgent):
        self.agent = agent
        self.logger = setup_file_logger(
            base_log_dir="./logs", logger_name=agent.agent_name
        )

    async def _safe_publish_event(
        self,
        *,
        event_queue: EventQueue,
        event,
        terminal_state_reached: bool,
    ) -> bool:
        """Publish a raw A2A event if the task is still active."""
        if terminal_state_reached:
            return False
        try:
            await event_queue.enqueue_event(event)
            return True
        except Exception as exc:
            self.logger.warning(f"Skipping late/closed event queue update: {exc}")
            return False

    async def _safe_publish_completion(
        self,
        *,
        updater: TaskUpdater,
        part: DataPart | TextPart,
        artifact_name: str,
    ) -> bool:
        """Publish final artifact and complete the task."""
        try:
            await updater.add_artifact([part], name=artifact_name)
            await updater.complete()
            return True
        except Exception as exc:
            self.logger.warning(f"Failed to publish completion artifact/status: {exc}")
            return False

    async def _safe_publish_status(
        self,
        *,
        updater: TaskUpdater,
        state: TaskState,
        message,
        final: bool = False,
    ) -> bool:
        """Publish a task status update."""
        try:
            await updater.update_status(state, message, final=final)
            return True
        except Exception as exc:
            self.logger.warning(
                f"Failed to publish status '{state.value}' update: {exc}"
            )
            return False

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        self.logger.info(f"Executing agent {self.agent.agent_name}")
        error = self._validate_request(context)
        if error:
            raise ServerError(error=InvalidParamsError())

        query = context.get_user_input()
        task = context.current_task

        if not task:
            task = new_task(context.message)
            await self._safe_publish_event(
                event_queue=event_queue,
                event=task,
                terminal_state_reached=False,
            )

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        last_text_sent = None
        terminal_state_reached = False

        async for item in self.agent.stream(query, task.context_id, task.id):
            # Agent-to-agent call may return fully formed A2A event wrappers.
            if hasattr(item, "root") and isinstance(item.root, SendStreamingMessageResponse):
                event = item.root.result
                if isinstance(event, (TaskStatusUpdateEvent | TaskArtifactUpdateEvent)):
                    await self._safe_publish_event(
                        event_queue=event_queue,
                        event=event,
                        terminal_state_reached=terminal_state_reached,
                    )
                continue

            if terminal_state_reached:
                self.logger.debug(
                    "Terminal state already reached; ignoring additional stream item."
                )
                continue

            self.logger.info(f"🔍 We received the item: {item}")
            is_task_complete = item["is_task_complete"]
            require_user_input = item["require_user_input"]

            if is_task_complete:
                self.logger.info(
                    f"🔍 {os.getpid()}: Completing with content: {item['content']}"
                )
                if item["response_type"] == "data":
                    part = DataPart(data=item["content"])
                else:
                    part = TextPart(text=item["content"])

                await self._safe_publish_completion(
                    updater=updater,
                    part=part,
                    artifact_name=f"{self.agent.agent_name}-result",
                )
                terminal_state_reached = True
                break

            if require_user_input:
                await self._safe_publish_status(
                    updater=updater,
                    state=TaskState.input_required,
                    message=new_agent_text_message(
                        item["content"], task.context_id, task.id
                    ),
                    final=True,
                )
                terminal_state_reached = True
                break

            # Working update path.
            if item["content"] != last_text_sent:
                self.logger.info(f"-----Continue updates!: {item['content']}")
                status_published = await self._safe_publish_status(
                    updater=updater,
                    state=TaskState.working,
                    message=new_agent_text_message(
                        item["content"],
                        task.context_id,
                        task.id,
                    ),
                )
                if status_published:
                    last_text_sent = item["content"]

    def _validate_request(self, context: RequestContext) -> bool:
        # TODO - see any requests for validations
        return False

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
