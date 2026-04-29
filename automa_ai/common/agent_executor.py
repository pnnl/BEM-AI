import os

from a2a.helpers.proto_helpers import (
    new_data_part,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    Part,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
    UnsupportedOperationError,
    InvalidParamsError,
)

from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.setup_logging import setup_file_logger


class GenericAgentExecutor(AgentExecutor):
    """Agent Executor used by modeling agents."""

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
        part: Part,
        artifact_name: str,
    ) -> bool:
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
    ) -> bool:
        try:
            await updater.update_status(state, message)
            return True
        except Exception as exc:
            self.logger.warning(
                f"Failed to publish status '{state}' update: {exc}"
            )
            return False

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        self.logger.info(f"Executing agent {self.agent.agent_name}")
        error = self._validate_request(context)
        if error:
            raise InvalidParamsError()

        query = context.get_user_input()
        task = context.current_task

        if not task:
            task = new_task_from_user_message(context.message)
            context.current_task = task
            await self._safe_publish_event(
                event_queue=event_queue,
                event=task,
                terminal_state_reached=False,
            )

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        last_text_sent = None
        terminal_state_reached = False

        async for item in self.agent.stream(query, task.context_id, task.id):
            if isinstance(item, StreamResponse):
                if item.HasField("status_update"):
                    await self._safe_publish_event(
                        event_queue=event_queue,
                        event=item.status_update,
                        terminal_state_reached=terminal_state_reached,
                    )
                elif item.HasField("artifact_update"):
                    await self._safe_publish_event(
                        event_queue=event_queue,
                        event=item.artifact_update,
                        terminal_state_reached=terminal_state_reached,
                    )
                elif item.HasField("task"):
                    await self._safe_publish_event(
                        event_queue=event_queue,
                        event=item.task,
                        terminal_state_reached=terminal_state_reached,
                    )
                elif item.HasField("message"):
                    await self._safe_publish_event(
                        event_queue=event_queue,
                        event=item.message,
                        terminal_state_reached=terminal_state_reached,
                    )
                continue

            if isinstance(item, (TaskStatusUpdateEvent, TaskArtifactUpdateEvent, Task)):
                await self._safe_publish_event(
                    event_queue=event_queue,
                    event=item,
                    terminal_state_reached=terminal_state_reached,
                )
                continue

            if terminal_state_reached:
                self.logger.debug(
                    "Terminal state already reached; ignoring additional stream item."
                )
                continue

            self.logger.info(f"Received the item: {item}")
            is_task_complete = item["is_task_complete"]
            require_user_input = item["require_user_input"]

            if is_task_complete:
                self.logger.info(
                    f"{os.getpid()}: Completing with content: {item['content']}"
                )
                if item["response_type"] == "data":
                    part = new_data_part(item["content"])
                else:
                    part = new_text_part(item["content"])

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
                    state=TaskState.TASK_STATE_INPUT_REQUIRED,
                    message=new_text_message(
                        text=item["content"],
                        context_id=task.context_id,
                        task_id=task.id,
                    ),
                )
                terminal_state_reached = True
                break

            if item["content"] != last_text_sent:
                self.logger.info(f"Continue updates: {item['content']}")
                status_published = await self._safe_publish_status(
                    updater=updater,
                    state=TaskState.TASK_STATE_WORKING,
                    message=new_text_message(
                        text=item["content"],
                        context_id=task.context_id,
                        task_id=task.id,
                    ),
                )
                if status_published:
                    last_text_sent = item["content"]

    def _validate_request(self, context: RequestContext) -> bool:
        return False

    async def cancel(
        self, request: RequestContext, event_queue: EventQueue
    ) -> Task | None:
        raise UnsupportedOperationError()
