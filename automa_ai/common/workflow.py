import json
import logging
import uuid
from enum import Enum
from typing import AsyncIterable, Any

import httpx
import networkx as nx
from a2a.client import A2AClient, create_text_message_object
from a2a.types import (
    AgentCard,
    SendStreamingMessageRequest,
    MessageSendParams,
    SendStreamingMessageResponse,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TaskState,
    SendStreamingMessageSuccessResponse,
)

from automa_ai.common.utils import get_agent_mcp_server_config
from automa_ai.mcp_servers import client

logger = logging.getLogger(__name__)


class Status(Enum):
    """Represents the status of a workflow and its associated node."""

    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    INITIALIZED = "INITIALIZED"


class WorkflowNode:
    """Represents a single node in a workflow graph
    Each node encapsulates a specific task to be executed, such as finding an agent or invoking an agent's capabilities.
    It manages its own state (e.g., READY, RUNNING, COMPLETED, PAUSE) and can execute its assigned task.
    """

    def __init__(
        self, task: str, node_key: str | None = None, node_label: str | None = None
    ):
        self.id = str(uuid.uuid4())
        self.node_key = node_key
        self.node_label = node_label
        self.task = task
        # self.history = history
        self.result = None
        self.state = Status.READY

    async def get_planner_resource(self) -> AgentCard | None:
        logger.info(f"Getting resource for node {self.id}")
        config = get_agent_mcp_server_config()
        async with client.init_session(
            config.host, config.port, config.transport
        ) as session:
            response = await client.find_resource(
                session, "resource://agent_cards/planner_agent"
            )
            data = json.loads(response.contents[0].text)
            if data:
                return AgentCard(**data["agent_card"])
            else:
                return None

    async def find_agent_for_task(self) -> AgentCard | None:
        logger.info(f"Finding agent for task - {self.task}")
        config = get_agent_mcp_server_config()
        async with client.init_session(
            config.host, config.port, config.transport
        ) as session:
            result = await client.find_agent(session, self.task)
            agent_card_json = json.loads(result.content[0].text)
            logger.info(f"Found agent {agent_card_json} for task {self.task}")
            return AgentCard(**agent_card_json)

    async def run_node(
        self, query: str, task_id: str, context_id: str, blackboard: dict
    ) -> AsyncIterable[dict[str, Any]]:
        logger.info(f"Executing node {self.id}")
        agent_card = None
        if self.node_key == "planner":
            agent_card = await self.get_planner_resource()
            if agent_card is None:
                agent_card = await self.find_agent_for_task()
        else:
            agent_card = await self.find_agent_for_task()

        #print(f"In the node, check out the blackboard: {blackboard}")

        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as httpx_client:
            # alternatively, a url would work too.
            a2a_client = A2AClient(httpx_client, agent_card)
            payload: dict[str, any] = {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "user",
                    "parts": [{"kind": "text", "text": str({"query": query, "blackboard": blackboard})}],
                    "taskId": None,
                    "contextId": context_id,
                }
            }
            msg = create_text_message_object(content=str({"query": query, "blackboard": blackboard}))
            request = SendStreamingMessageRequest(
                id=str(uuid.uuid4()), params=MessageSendParams(**payload)
            )
            response_stream = a2a_client.send_message_streaming(request)
            async for chunk in response_stream:
                # print(f"this is error chunk: {chunk}")
                logger.error(f"chunk returned {chunk}")
                # Save the artifact as a result of the node
                if isinstance(chunk.root, SendStreamingMessageResponse) and isinstance(
                    chunk.root.result, TaskArtifactUpdateEvent
                ):
                    artifact = chunk.root.result.artifact
                    self.results = artifact
                yield chunk


class WorkflowGraph:
    """Represents a graph of workflow nodes."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self.nodes = {}
        self.latest_node = None
        self.node_type = None
        self.state = Status.INITIALIZED
        self.blackboard = {}
        self.paused_node_id = None

    def add_node(self, node) -> None:
        logger.info(f"Adding one {node.id}")
        self.graph.add_node(node.id, query=node.task)
        self.nodes[node.id] = node
        self.latest_node = node.id

    def add_edge(self, from_node_id: str, to_node_id: str) -> None:
        if from_node_id not in self.nodes or to_node_id not in self.nodes:
            raise ValueError("Invalid node IDs")
        self.graph.add_edge(from_node_id, to_node_id)

    def update_blackboard(self, blackboard):
        self.blackboard = {**self.blackboard, **blackboard}
        #print(self.blackboard)

    async def run_workflow(
        self, start_node_id: str | None = None
    ) -> AsyncIterable[dict[str, any]]:
        logger.info("Executing workflow graph")
        if not start_node_id or start_node_id not in self.nodes:
            start_nodes = [n for n, d in self.graph.in_degree() if d == 0]
        else:
            start_nodes = [self.nodes[start_node_id].id]

        applicable_graph = set()

        for node_id in start_nodes:
            applicable_graph.add(node_id)
            applicable_graph.update(nx.descendants(self.graph, node_id))

        complete_graph = list(nx.topological_sort(self.graph))
        sub_graph = [n for n in complete_graph if n in applicable_graph]
        logger.info(f"Sub graph {sub_graph} size {len(sub_graph)}")
        self.state = Status.RUNNING
        # Alternative is to loop over all nodes, but we only need the connected nodes.
        for node_id in sub_graph:
            node = self.nodes[node_id]
            node.state = Status.RUNNING
            query = self.graph.nodes[node_id].get("query")
            task_id = self.graph.nodes[node_id].get("task_id")
            context_id = self.graph.nodes[node_id].get("context_id")
            async for chunk in node.run_node(query, task_id, context_id, self.blackboard):
                # When the workflow node is paused, do not yield any chunks
                # but, let the loop complete.
                if node.state != Status.PAUSED:
                    if isinstance(chunk.root, SendStreamingMessageSuccessResponse) and (
                        isinstance(chunk.root.result, TaskStatusUpdateEvent)
                    ):
                        task_status_event = chunk.root.result
                        context_id = task_status_event.context_id
                        logger.info(
                            "🧠 Workflow task status update event: %s",
                            task_status_event,
                        )

                        if (
                            task_status_event.status.state == TaskState.input_required
                            and context_id
                        ):
                            node.state = Status.PAUSED
                            self.state = Status.PAUSED
                            self.paused_node_id = node.id
                    yield chunk
            if self.state == Status.PAUSED:
                break
            if node.state == Status.RUNNING:
                node.state = Status.COMPLETED
        if self.state == Status.RUNNING:
            self.state = Status.COMPLETED

    def set_node_attribute(self, node_id, attribute, value) -> None:
        nx.set_node_attributes(self.graph, {node_id: value}, attribute)

    def set_node_attributes(self, node_id, attr_val) -> None:
        nx.set_node_attributes(self.graph, {node_id: attr_val})

    def is_empty(self) -> bool:
        return self.graph.number_of_nodes() == 0
