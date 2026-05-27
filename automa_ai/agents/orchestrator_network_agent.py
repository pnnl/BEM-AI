import logging
from typing import AsyncIterable, Any, Dict, Optional

from a2a.types import (
    SendStreamingMessageSuccessResponse,
    TaskStatusUpdateEvent,
    TaskState,
    TaskArtifactUpdateEvent, DataPart, TextPart,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel

from automa_ai.agents import GenericLLM
from automa_ai.common.normalization import sanitize_blackboard_update
from automa_ai.common.response_parser import extract_and_parse_json
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.workflow import WorkflowGraph, WorkflowNode, Status
from automa_ai.observability.notifier import AgentEvent, EventNotifier, NoOpEventNotifier


logger = logging.getLogger(__name__)

class OrchestratorConfig(BaseModel):
    chat_model: GenericLLM
    model_name: str
    instruction: str
    model_base_url: str | None = None
    logging_config: Optional[Dict[str, Any]] = None

class OrchestratorNetworkAgent(BaseAgent):
    """
    Orchestrator Agent - The agent manages one task workflow.
    In the end, the agent will review the final task and decide whether it needs to reboot planner
    or use generate summary
    A blackboard is setup for sharing among agents.

    """

    def __init__(
            self,
            agent_name: str,
            description: str,
            instructions: str,
            chat_model: BaseChatModel,
            event_notifier: EventNotifier | None = None,
        ):
        super().__init__(
            agent_name=agent_name,
            description=description,
            content_types=["text", "text/plain"],
        )
        self.graph: WorkflowGraph | None = None
        self.results = []
        self.task_blackboard = (
            {}
        )  # shared memory on task specs, data format shall come from planner's response
        self.query_history = []
        self.context_id = None
        self.summary_instruction = instructions
        self.chat_model = chat_model
        self.event_notifier = event_notifier or NoOpEventNotifier()

    async def _emit_event(
        self,
        event_type: str,
        message: str,
        *,
        source: str,
        target: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.event_notifier.emit(
            AgentEvent(
                event_type=event_type,
                source=source,
                target=target,
                session_id=session_id,
                task_id=task_id,
                message=message,
                metadata=metadata or {},
            )
        )

    async def invoke(
        self,
        query,
        context_id,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        # no actual usage.
        pass

    async def review_task_outcome(self) -> str:
        pass

    async def generate_summary(self) -> str:
        prompt = PromptTemplate.from_template(self.summary_instruction)
        summary_chain = prompt | self.chat_model | StrOutputParser()
        response = summary_chain.invoke({"query": self.query_history, "blackboard": self.task_blackboard, "results": self.results})
        return response

#    def answer_user_question(self, question) -> dict:
#        # autonomous questions and answer workflow
#        # if used internally within the agents instead
#        # involve human in the loop.
#        try:
#            llm = ChatOllama(model="llama3.1:8b", temperature=0)
#            prompt = PromptTemplate.from_template(QA_COT_PROMPT)
#            summary_chain = prompt | llm | JsonOutputParser()
#            response = summary_chain.invoke(
#                {
#                    "model_info": self.task_blackboard,
#                    "conversation_history": str(self.query_history),
#                    "model_question": question,
#                }
#            )
#            return response
#        except Exception as e:
#            logger.info(f"Error answering user question: {e}")
#        return {"can_answer": "no", "answer": "Cannot answer based on provided context"}

    def set_node_attributes(self, node_id, task_id=None, context_id=None, query=None):
        attr_val = {}
        if task_id:
            attr_val["task_id"] = task_id
        if context_id:
            attr_val["context_id"] = context_id
        if query:
            attr_val["query"] = query

        self.graph.set_node_attributes(node_id, attr_val)

    def add_graph_node(
        self,
        task_id,
        context_id,
        query: str,
        node_id: str = None,
        node_key: str = None,
        node_label: str = None,
    ) -> WorkflowNode:
        """Add a node to the graph."""
        node = WorkflowNode(
            task=query,
            node_key=node_key,
            node_label=node_label,
            event_notifier=self.event_notifier,
        )
        self.graph.add_node(node)
        if node_id:
            self.graph.add_edge(node_id, node.id)
        self.set_node_attributes(node.id, task_id, context_id, query)
        return node

    def clear_state(self):
        self.graph = None
        self.results.clear()
        self.task_blackboard.clear()
        self.query_history.clear()

    async def stream(self, query, context_id, task_id, user_id: str | None = None, metadata: dict[str, Any] | None = None) -> AsyncIterable[dict[str, Any]]:
        """Execute and stream response."""
        logger.info(
            f"Running {self.agent_name} stream for session {context_id}, task {task_id} - {query}"
        )
        if not query:
            raise ValueError("Query cannot be empty")
        if self.context_id != context_id:
            # Clear state when the context changes
            self.clear_state()
            self.context_id = context_id

        self.query_history.append(query)
        start_node_id = None
        # Graph does not exist, start a new graph with planner node.
        if not self.graph:
            self.graph = WorkflowGraph(event_notifier=self.event_notifier)
            await self._emit_event(
                "session_started",
                "Started a new orchestrated workflow session.",
                source=self.agent_name,
                session_id=context_id,
                task_id=task_id,
                metadata={"query": query},
            )
            planner_node = self.add_graph_node(
                task_id=task_id,
                context_id=context_id,
                query=query,
                node_key="planner",
                node_label="planner",
            )
            start_node_id = planner_node.id
        # Pause state is when the agent might need more information
        elif self.graph.state == Status.PAUSED:
            start_node_id = self.graph.paused_node_id
            self.set_node_attributes(node_id=start_node_id, query=query)
            await self._emit_event(
                "session_resumed",
                "Resumed a paused workflow session with new user input.",
                source=self.agent_name,
                session_id=context_id,
                task_id=task_id,
                metadata={"query": query, "paused_node_id": start_node_id},
            )

        # This loop can be avoided if the workflow graph is dynamic or
        # is built from the results of the planner when the planner itself
        # is not a part of the graph.
        while True:
            # Set attributes on the node so we propagate task and context
            self.set_node_attributes(
                node_id=start_node_id, task_id=task_id, context_id=context_id
            )
            # Resume workflow, used when the workflow nodes are updated.
            should_resume_workflow = False
            async for chunk in self.graph.run_workflow(start_node_id=start_node_id):
                logger.info(chunk)
                if isinstance(chunk.root, SendStreamingMessageSuccessResponse):
                    # The graph node returned TaskStatusUpdateEvent
                    # Check if the node is complete and continue to the next node
                    if isinstance(chunk.root.result, TaskStatusUpdateEvent):
                        task_status_event = chunk.root.result
                        context_id = task_status_event.context_id
                        logger.info(
                            f"Streaming message from task updates: {task_status_event}"
                        )
                        # If the node is completed, then move to the next node
                        if (
                            task_status_event.status.state == TaskState.completed
                            and context_id
                        ):
                            # yield chunk
                            continue
                        if task_status_event.status.state == TaskState.input_required:
                            question = task_status_event.status.message.parts[
                                0
                            ].root.text
                            start_node_id = self.graph.paused_node_id
                            yield {
                                "response_type": "text",
                                "is_task_complete": False,
                                "require_user_input": True,
                                "content": question,
                            }

                        if task_status_event.status.state == TaskState.working:
                            message = task_status_event.status.message.parts[0].root.text
                            # print(f"🧠 Agent Thinking: {message}")
                            yield {
                                "response_type": "text",
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": f"🧠 Agent Reasoning: {message}",
                            }
                    # The graph node returned TaskArtifactUpdateEvent
                    # Store the node and continue
                    if isinstance(chunk.root.result, TaskArtifactUpdateEvent):
                        artifact = chunk.root.result.artifact
                        agent_name = artifact.name
                        # self.results.append(artifact)
                        if isinstance(artifact.parts[0].root, TextPart):
                            text = artifact.parts[0].root.text
                            report_text = f"{agent_name}:\n\n {text}"
                            if text.startswith("<think>"):
                                # attempt extract
                                _, parsed = extract_and_parse_json(text)
                                if isinstance(parsed, dict):
                                    if parsed.get("status") and parsed["status"] == "completed" and parsed.get("blackboard"):
                                        # if the returned text generated response and response status is completed, update the blackboard.
                                        sanitized = sanitize_blackboard_update(agent_name, parsed.get("blackboard"))
                                        if sanitized:
                                            self.graph.update_blackboard(sanitized)
                                            await self._emit_event(
                                                "blackboard_updated",
                                                f"Agent '{agent_name}' updated the shared blackboard.",
                                                source=agent_name,
                                                target="blackboard",
                                                session_id=context_id,
                                                task_id=task_id,
                                                metadata={"delta": sanitized},
                                            )
                            self.results.append(text)
                            yield {
                                "response_type": "text",
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": report_text,
                            }
                        # if artifact.name == "Planner Agent-result":
                        if isinstance(artifact.parts[0].root, DataPart):
                            artifact_data = artifact.parts[0].root.data
                            response_text = ""
                            # update blackboard
                            if artifact_data.get("blackboard"):
                                sanitized = sanitize_blackboard_update(agent_name, artifact_data.get("blackboard"))
                                if sanitized:
                                    self.graph.update_blackboard(sanitized)
                                    await self._emit_event(
                                        "blackboard_updated",
                                        f"Agent '{agent_name}' updated the shared blackboard.",
                                        source=agent_name,
                                        target="blackboard",
                                        session_id=context_id,
                                        task_id=task_id,
                                        metadata={"delta": sanitized},
                                    )
                                    response_text += f"Backboard update: {sanitized} \n\n"
                            # update history
                            if artifact_data.get("results"):
                                self.results.append(artifact.parts[0].root.data.get("results"))
                            else:
                                self.results.append(artifact.parts[0].root)
                            # any task detected.
                            if artifact.parts[0].root.data.get("tasks"):
                                response_text += "Generated Task(s): \n"
                                # Planning agent returned data, update graph.
                                logger.info(
                                    f"Updating workflow with {artifact_data} task nodes"
                                )
                                # Define the edges
                                current_node_id = start_node_id
                                # print(artifact_data)
                                await self._emit_event(
                                    "planner_tasks_generated",
                                    "Planner generated workflow tasks.",
                                    source=agent_name,
                                    target="workflow",
                                    session_id=context_id,
                                    task_id=task_id,
                                    metadata={"tasks": artifact_data["tasks"]},
                                )
                                for idx, task_data in enumerate(artifact_data["tasks"]):
                                    # distribute relevant modeling tasks.
                                    response_text += f"- {task_data} \n"
                                    node = self.add_graph_node(
                                        task_id=str(idx),
                                        context_id=context_id,
                                        query=task_data["description"],
                                        node_id=current_node_id,
                                    )
                                    current_node_id = node.id
                                    # Restart graph from the newly inserted subgraph state
                                    # Start from the new node just created
                                    if idx == 0:
                                        should_resume_workflow = True
                                        start_node_id = node.id
                            yield {
                                "response_type": "text",
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": f"{agent_name}: \n\n {response_text}",
                            }

                        else:
                            self.results.append(artifact)
                            # Not planner but artifacts from other tasks,
                            # Continue to the next node in the workflow
                            # client does not get the artifact,
                            # a summary is shown at the end of the workflow.
                            # print(artifact)
                            continue
                            # When the workflow needs to be resumed, do not yield partial.

                if not should_resume_workflow:
                    logger.info("No workflow resume detected, yielding chunk")
                    # A user may respond in here.
                    # Yield partial execution
                    yield {
                        "response_type": "text",
                        "is_task_complete": False,
                        "require_user_input": False,
                        "content": "...",
                    }

                # print("Resume Workflow", should_resume_workflow)
            # The graph is complete and no updates, so okay to break from the loop.
            if not should_resume_workflow:
                logger.info(
                    "Workflow iteration complete and no restart requested. Exiting main loop."
                )
                break
            else:
                # Readable logs
                logger.info("Restarting workflow loop.")
        if self.graph.state == Status.COMPLETED:
            # All individual actions completed, now generate the summary
            logger.info(f"Generating summary for {len(self.results)} results")
            summary = await self.generate_summary()
            await self._emit_event(
                "workflow_completed",
                "Workflow completed successfully and generated a summary.",
                source=self.agent_name,
                session_id=context_id,
                task_id=task_id,
                metadata={"summary": summary},
            )
            self.clear_state()
            logger.info(f"Summary: {summary}")
            yield {
                "response_type": "text",
                "is_task_complete": True,
                "require_user_input": False,
                "content": summary,
            }
