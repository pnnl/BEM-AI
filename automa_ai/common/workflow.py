import json
import logging
import uuid
from enum import Enum
from typing import Any, AsyncIterable

import httpx
import networkx as nx

from google.protobuf.json_format import ParseDict

from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import new_text_message
from a2a.types import (
    AgentCard,
    Role,
    SendMessageRequest,
    StreamResponse,
    TaskState,
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
    """Represents a single node in a workflow graph."""

    def __init__(
        self, task: str, node_key: str | None = None, node_label: str | None = None
    ):
        self.id = str(uuid.uuid4())
        self.node_key = node_key
        self.node_label = node_label
        self.task = task
        self.result = None
        self.state = Status.READY

    async def get_planner_resource(self) -> AgentCard | None:
        logger.info("Getting resource for node %s", self.id)
        config = get_agent_mcp_server_config()
        async with client.init_session(
            config.host, config.port, config.transport
        ) as session:
            response = await client.find_resource(
                session, "resource://agent_cards/planner_agent"
            )
            data = json.loads(response.contents[0].text)
            if data:
                return ParseDict(data["agent_card"], AgentCard())
            return None

    async def find_agent_for_task(self) -> AgentCard | None:
        logger.info("Finding agent for task - %s", self.task)
        config = get_agent_mcp_server_config()
        async with client.init_session(
            config.host, config.port, config.transport
        ) as session:
            result = await client.find_agent(session, self.task)
            agent_card_json = json.loads(result.content[0].text)
            logger.info(
                "Found agent %s for task %s", agent_card_json, self.task
            )
            return ParseDict(agent_card_json, AgentCard())

    async def run_node(
        self, query: str, task_id: str, context_id: str, blackboard: dict
    ) -> AsyncIterable[StreamResponse]:
        logger.info("Executing node %s", self.id)
        if self.node_key == "planner":
            agent_card = await self.get_planner_resource()
            if agent_card is None:
                agent_card = await self.find_agent_for_task()
        else:
            agent_card = await self.find_agent_for_task()

        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as httpx_client:
            a2a_client = await create_client(
                agent_card,
                client_config=ClientConfig(httpx_client=httpx_client),
            )
            request = SendMessageRequest(
                message=new_text_message(
                    text=str({"query": query, "blackboard": blackboard}),
                    context_id=context_id,
                    task_id=task_id,
                    role=Role.ROLE_USER,
                )
            )
            async for chunk in a2a_client.send_message(request):
                logger.info("chunk returned %s", chunk)
                if chunk.HasField("artifact_update"):
                    self.result = chunk.artifact_update.artifact
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
        logger.info("Adding one %s", node.id)
        self.graph.add_node(node.id, query=node.task)
        self.nodes[node.id] = node
        self.latest_node = node.id

    def add_edge(self, from_node_id: str, to_node_id: str) -> None:
        if from_node_id not in self.nodes or to_node_id not in self.nodes:
            raise ValueError("Invalid node IDs")
        self.graph.add_edge(from_node_id, to_node_id)

    def update_blackboard(self, blackboard):
        self.blackboard = {**self.blackboard, **blackboard}

    async def run_workflow(
        self, start_node_id: str | None = None
    ) -> AsyncIterable[StreamResponse]:
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
        logger.info("Sub graph %s size %s", sub_graph, len(sub_graph))
        self.state = Status.RUNNING
        for node_id in sub_graph:
            node = self.nodes[node_id]
            node.state = Status.RUNNING
            query = self.graph.nodes[node_id].get("query")
            task_id = self.graph.nodes[node_id].get("task_id")
            context_id = self.graph.nodes[node_id].get("context_id")
            async for chunk in node.run_node(
                query, task_id, context_id, self.blackboard
            ):
                if node.state != Status.PAUSED:
                    if chunk.HasField("status_update"):
                        task_status_event = chunk.status_update
                        context_id = task_status_event.context_id
                        logger.info(
                            "Workflow task status update event: %s",
                            task_status_event,
                        )

                        if (
                            task_status_event.status.state
                            == TaskState.TASK_STATE_INPUT_REQUIRED
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
