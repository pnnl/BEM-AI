import logging
from typing import Dict, AsyncIterable, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from pydantic import BaseModel

from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.retriever import BaseRetriever
from automa_ai.common.types import ServerConfig
from automa_ai.metrics.collector import MetricsCollector
from automa_ai.metrics.extractor import extract_metrics_from_chunk

memory = MemorySaver()
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)-8s | "
                           "%(module)s:%(funcName)s:%(lineno)d - %(message)s")
logger = logging.getLogger(__name__)

class GenericLangGraphChatAgent(BaseAgent):
    """A generic LangGraph react agent"""

    def __init__(
        self,
        agent_name: str,
        description: str,
        instructions: str,
        chat_model: BaseChatModel,
        response_format: type[BaseModel] | None,
        mcp_servers: Dict[str, ServerConfig] | None = None,
        retriever: BaseRetriever | None = None,
        enable_metrics: bool = False,
        debug: bool = False
    ):

        logger.info("Initializing a LangGraph react agent")
        # Remove all empty strings
        super().__init__(
            agent_name=agent_name,
            description=description,
            content_types=["text", "text/plain"],
        )
        self.model = chat_model
        self.response_format = response_format
        self.instructions = instructions
        self.client = None
        self.graph = None
        self.mcp_servers = mcp_servers
        self.retriever = retriever
        self.metrics = None
        self.debug = debug
        if enable_metrics:
            self.metrics = MetricsCollector()

    async def init_graph(self):
        """Load the agent graph"""
        logger.info(f"Initializing {self.agent_name} metadata")
        if self.mcp_servers:
            # Loading mcp server clients.
            logger.info(f"Subscribe to MCPs through sse")

            self.client = MultiServerMCPClient(
                {
                    server_name: {
                        "url": f"{self.mcp_servers[server_name].url}/sse",
                        "transport": "sse",
                    }
                    for server_name in self.mcp_servers
                }
            )

        tools = []
        if self.client:
            tools = await self.client.get_tools()
            for tool in tools:
                if self.debug:
                    print(self.agent_name, f"Loaded tools {tool.name}")
                logger.info(f"Loaded tools {tool.name}")

        self.graph = create_agent(
            self.model,
            checkpointer=memory,
            system_prompt=self.instructions,
            # response_format=self.response_format,
            tools=tools
        )

    async def invoke(self, query, sessionId):
        config = {"configurable": {"thread_id": sessionId}}
        if not self.graph:
            await self.init_graph()
        response = await self.graph.ainvoke({"messages": [("user", query)]}, config)
        return response

    async def stream(self, query, session_id, task_id) -> AsyncIterable[dict[str, Any]]:
        # If selected to track metrics
        if self.metrics:
            if self.metrics.current_query_id and self.metrics.current_query_id != query:
                # If a new task, write out the previous task.
                print(self.metrics.summary_for_query(self.metrics.current_query_id))
            self.metrics.start_query(task_id)
        # Optional RAG retrieval
        context = ""
        if self.retriever:
            context = await self.retriever.asimilarity_search_by_vector(query)

        # Build augmented user query
        if context:
            augmented_query = f"""
                You are given the following context from the knowledge base:
                {context}
                User query:
                {query}
            """
            if self.debug:
                print(augmented_query)
                logger.info(f"Augmented query: {augmented_query}")
        else:
            augmented_query = query

        # Assemble message
        inputs = {"messages": [{"role": "user", "content": augmented_query}]}
        config = {"configurable": {"thread_id": session_id}}
        logger.info(
            f"Running planner agent stream for session {session_id} {task_id} with input {query}"
        )
        if not self.graph:
            await self.init_graph()
        # seen_messages = set()
        # Collect all streaming messages first
        async for chunk in self.graph.astream(inputs, config, stream_mode="messages"):
            if self.debug:
                print("Getting the chunk", chunk)
            ck, meta = chunk
            if isinstance(ck, AIMessageChunk):
                if self.metrics:
                    # Record tracking
                    if ck.response_metadata:
                        self.metrics.add(extract_metrics_from_chunk(
                            ck,
                            session_id=session_id,
                            query_id=self.metrics.current_query_id
                        ))
                if ck.content:
                    content = ck.content
                    response_metadata = ck.response_metadata

                    if content and isinstance(content, list):
                        # likely this is a gemini responses
                        content = content[0]
                        if response_metadata and response_metadata['model_provider'] == "google_genai":
                            # in this case, it is likely a json inside a list
                            if content["type"] == "text" and content["text"]:
                                content = content["text"]
                    # content = content.strip()

                    yield {
                        "response_type": "text",
                        "is_task_complete": False,
                        "require_user_input": False,
                        "content": content,
                    }
                elif ck.tool_calls:
                    tool_call_str = ""
                    for tool_call in ck.tool_calls:
                        tool_call_str += f"Making tool calls: **{tool_call.get('name')}**:\n\n"
                        tool_call_str += f"**Arguments**: {tool_call.get('args')}\n\n"

                    yield {
                        "response_type": "text",
                        "is_task_complete": False,
                        "require_user_input": False,
                        "content": tool_call_str,
                    }
            elif isinstance(ck, ToolMessage):
                if ck.content:
                    content = f"**Tool {ck.name} responded**: {ck.content}\n\n"
                    yield {
                        "response_type": "text",
                        "is_task_complete": False,
                        "require_user_input": False,
                        "content": content,
                    }
                else:
                    # Fall back
                    yield {
                        "response_type": "text",
                        "is_task_complete": False,
                        "require_user_input": False,
                        "content": f"Tool call {ck.name} has no content return or failed. check logs.",
                    }
