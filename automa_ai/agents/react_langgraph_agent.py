import re
from json import JSONDecodeError
from typing import Dict, AsyncIterable, Any, Callable, List
from asyncio import Queue

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from pydantic import BaseModel

from automa_ai.agents.remote_agent import (
    SubAgentSpec,
    make_subagent_tool,
    StreamEvent,
    build_subagent_delegation_instruction,
    reset_subagent_context_id,
    reset_subagent_user_id,
    set_subagent_context_id,
    set_subagent_user_id,
)
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.response_parser import extract_and_parse_json
from automa_ai.common.setup_logging import setup_file_logger
from automa_ai.common.types import ServerConfig
from automa_ai.common.utils import map_server_config_to_mcp_connection


memory = MemorySaver()
_TOOL_RESPONSE_ERROR_MARKERS = (
    "error",
    "exception",
    "traceback",
    "failed",
    "failure",
)


def _should_emit_tool_response(tool_name: str | None, content: Any) -> bool:
    """Return whether a tool response should be streamed to the user."""
    if tool_name != "load_skill":
        return True
    normalized = str(content).lower()
    return any(marker in normalized for marker in _TOOL_RESPONSE_ERROR_MARKERS)


class GenericLangGraphReactAgent(BaseAgent):
    """A generic LangGraph react agent"""

    def __init__(
        self,
        agent_name: str,
        description: str,
        instructions: str,
        chat_model: BaseChatModel,
        response_format: type[BaseModel] | None,
        mcp_servers: Dict[str, ServerConfig] | None = None,
        retriever: Callable | None = None,
        subagents: List[SubAgentSpec] | None = None,
        debug: bool = False,
    ):

        # Remove all empty strings
        super().__init__(
            agent_name=agent_name,
            description=description,
            content_types=["text", "text/plain"],
        )
        self.logger = setup_file_logger(base_log_dir="./logs", logger_name=agent_name)
        self.model = chat_model
        self.response_format = response_format
        self.instructions = instructions
        self.client = None
        self.graph = None
        self.mcp_servers = mcp_servers
        self.retriever = retriever
        self.debug = debug
        self.subagents = subagents

    async def init_graph(self, emitter: Callable[[StreamEvent], None]):
        """Load the agent graph -> this can be overridden to support static multi-agent setup."""
        self.logger.info(f"Initializing {self.agent_name} metadata")
        if self.mcp_servers:
            # Loading mcp server clients.
            self.logger.info(f"Subscribe to MCPs through sse")

            self.client = MultiServerMCPClient(
                {
                    server_name: map_server_config_to_mcp_connection(
                        self.mcp_servers[server_name]
                    )
                    for server_name in self.mcp_servers
                }
            )

        tools = []
        if self.client:
            tools = await self.client.get_tools()
            for tool in tools:
                if self.debug:
                    print(self.agent_name, f"Loaded tools {tool.name}")
                self.logger.info(f"Loaded tools {tool.name}")

        if self.subagents:
            for subagent in self.subagents:
                tools.append(make_subagent_tool(subagent, emitter))
            # build up the instruction
            self.instructions = (
                f"{self.instructions}\n\n"
                f"{build_subagent_delegation_instruction(self.subagents)}"
            )

        self.graph = create_agent(
            self.model,
            checkpointer=memory,
            system_prompt=self.instructions,
            # response_format=self.response_format,
            tools=tools,
        )

    async def invoke(
        self,
        query,
        context_id,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        config = self._build_runnable_config(context_id, user_id, metadata=metadata)
        # queue for tool/subagent streaming
        subagent_event_queue: Queue[StreamEvent] = Queue()

        def emit_subagent_event(e: StreamEvent):
            """
            Called by tools / subagents to stream intermediate output.
            Must be non-blocking.
            """
            subagent_event_queue.put_nowait(e)

        emitter = emit_subagent_event

        if not self.graph:
            await self.init_graph(emitter)
        context_id_token = set_subagent_context_id(context_id)
        user_id_token = set_subagent_user_id(user_id)
        try:
            response = await self.graph.ainvoke(
                {"messages": [("user", query)]},
                config,
            )
        finally:
            reset_subagent_user_id(user_id_token)
            reset_subagent_context_id(context_id_token)
        return response

    async def stream(
        self,
        query,
        context_id,
        task_id,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterable[dict[str, Any]]:
        # use to track the tool call steps
        active_tool_calls = 0
        # queue for tool/subagent streaming
        subagent_event_queue: Queue[StreamEvent] = Queue()

        def emit_subagent_event(e: StreamEvent):
            """
            Called by tools / subagents to stream intermediate output.
            Must be non-blocking.
            """
            subagent_event_queue.put_nowait(e)

        emitter = emit_subagent_event

        # Optional RAG retrieval
        context = ""
        if self.retriever:
            context = await self.retriever(query)

        # Build augmented user query
        if context:
            augmented_query = f"""
                You are given the following context from the knowledge base:
                {context}
                User query:
                {query}
            """
        else:
            augmented_query = query

        # Assemble message
        inputs = {"messages": [{"role": "user", "content": augmented_query}]}

        config = self._build_runnable_config(context_id, user_id, metadata=metadata)
        self.logger.info(
            f"Running planner agent stream for session {context_id} {task_id} with input {query}"
        )
        if not self.graph:
            await self.init_graph(emitter)

        async def graph_stream():
            graph_iterator = self.graph.astream(
                inputs,
                config,
                stream_mode="updates",
            ).__aiter__()
            try:
                while True:
                    context_id_token = set_subagent_context_id(context_id)
                    user_id_token = set_subagent_user_id(user_id)
                    try:
                        graph_chunk = await anext(graph_iterator)
                    except StopAsyncIteration:
                        return
                    finally:
                        # Reset before yielding to the caller so an early-stop
                        # cannot leave request context scoped to this request.
                        reset_subagent_user_id(user_id_token)
                        reset_subagent_context_id(context_id_token)
                    yield graph_chunk
            finally:
                close = getattr(graph_iterator, "aclose", None)
                if close is not None:
                    await close()

        # seen_messages = set()
        # Collect all streaming messages first
        async for chunk in graph_stream():
            # surface local tool/subagent streaming
            while not subagent_event_queue.empty():
                event = subagent_event_queue.get_nowait()
                # Build informative content
                content_str = f"\n\n[{event.source}] "

                if event.metadata and event.metadata.get("final"):
                    content_str += "(final) "
                content_str += event.content

                yield {
                    "response_type": "text",
                    "is_task_complete": False,
                    "require_user_input": False,
                    "content": content_str,
                }

            if self.debug:
                print("Getting the chunk", chunk)
            for step, data in chunk.items():
                if step == "model":
                    if "messages" in data:
                        # Take out the last AI Message
                        message = data["messages"][-1]
                        self.logger.info(f"Streaming message: {message}")
                        self.logger.info(
                            f"Message type is: {type(message)}, and message is: {isinstance(message, AIMessage)} item type is: {type(data)}"
                        )
                        if isinstance(message, AIMessage) and message.content:
                            content = message.content
                            response_metadata = message.response_metadata
                            if content and isinstance(content, list):
                                # likely this is a gemini responses
                                content = content[0]
                                if (
                                    response_metadata
                                    and response_metadata["model_provider"]
                                    == "google_genai"
                                ):
                                    # in this case, it is likely a json inside a list
                                    if content["type"] == "text" and content["text"]:
                                        content = content["text"]
                            content = content.strip()
                            if self.debug:
                                print(f"Streaming content: {content}")
                            if content.startswith("<think>") or content.endswith(
                                "</think>"
                            ):
                                # Remove <think>...</think> (including newlines and spaces around it)
                                content = re.sub(
                                    r"<think>.*?</think>\s*",
                                    "",
                                    content,
                                    flags=re.DOTALL,
                                )
                            # Skip ToolMessage and HumanMessage and make sure there is content in the AI message (not a tool calling AI message, which typically has no content.)
                            try:
                                _, parsed = extract_and_parse_json(content)
                                # This only works with the llama3.1:8b when it explicitly gives CHAIN OF THOUGHT PROCESS in the output
                                # despite the prompts ask only JSON
                                # print(self.agent_name, ": ", content)
                                # print("parsed: ", parsed)
                                if isinstance(parsed, dict):
                                    if parsed.get("type") == "function":
                                        # Skip this because we need to force this into function call.
                                        continue
                                    if not parsed.get("status"):
                                        # case when work is completed and AI is giving the json
                                        # BIG ASSUMPTION HERE! This means unless its output, all recursive generation
                                        # including MCPs shall returning in String format.
                                        yield {
                                            "response_type": "data",
                                            "is_task_complete": True,
                                            "require_user_input": False,
                                            "content": parsed,
                                        }
                                    if parsed.get("status") == "completed":
                                        self.logger.info(f"completed task: {parsed}")
                                        yield {
                                            "response_type": "data",
                                            "is_task_complete": True,
                                            "require_user_input": False,
                                            "content": parsed,
                                        }
                                    elif parsed.get("status") == "input_required":
                                        yield {
                                            "response_type": "text",
                                            "is_task_complete": False,
                                            "require_user_input": True,
                                            "content": parsed["question"],
                                        }
                                    else:
                                        # we don't know what is the status, it could be just thinking or asking user to clarify
                                        if content.startswith("<think>"):
                                            yield {
                                                "response_type": "text",
                                                "is_task_complete": False,
                                                "require_user_input": False,
                                                "content": content,
                                            }
                                        else:
                                            yield {
                                                "response_type": "text",
                                                "is_task_complete": False,
                                                "require_user_input": True,
                                                "content": parsed["question"],
                                            }
                                else:
                                    yield {
                                        "response_type": "text",
                                        "is_task_complete": False,
                                        "require_user_input": False,
                                        "content": content,
                                    }
                            except JSONDecodeError as jde:
                                if self.debug:
                                    print(
                                        f"Failed parsing JSON data, error message: {jde}"
                                    )
                                self.logger.info(
                                    f"Failed parsing JSON data, error message: {jde}"
                                )
                                if content.startswith("<think>"):
                                    # There should be a better way to handle this through network but
                                    # Let's just settle with a simple print for now.
                                    yield {
                                        "response_type": "text",
                                        "is_task_complete": False,
                                        "require_user_input": False,
                                        "content": content,
                                    }
                                else:
                                    yield {
                                        "response_type": "text",
                                        "is_task_complete": False,
                                        "require_user_input": True,
                                        "content": content,
                                    }
                            except AssertionError as ae:
                                if self.debug:
                                    print(
                                        f"Failed matching the ai message, error message: {ae}"
                                    )
                                # cannot parse the message to JSON. return raw msg and ask for user input
                                self.logger.info(
                                    f"Failed matching the ai message, error message: {ae}"
                                )
                                yield {
                                    "response_type": "text",
                                    "is_task_complete": False,
                                    "require_user_input": True,
                                    "content": content,
                                }
                            except Exception as e:
                                if self.debug:
                                    print(
                                        f"Failed matching the ai message, error message: {e}"
                                    )
                                self.logger.info(
                                    f"Failed matching the ai message, error message: {e}"
                                )
                                if content.startswith("<think>"):
                                    # There should be a better way to handle this through network but
                                    # Let's just settle with a simple print for now.
                                    yield {
                                        "response_type": "text",
                                        "is_task_complete": False,
                                        "require_user_input": False,
                                        "content": content,
                                    }
                                else:
                                    yield {
                                        "response_type": "text",
                                        "is_task_complete": False,
                                        "require_user_input": True,
                                        "content": content,
                                    }
                            # Fall back
                            yield {
                                "is_task_complete": False,
                                "require_user_input": True,
                                "content": f"Unable to determine next steps. Please try again. item {data['messages'][-1]}",
                            }
                        elif isinstance(message, AIMessage) and message.tool_calls:
                            tool_call_str = ""
                            for tool_call in message.tool_calls:
                                tool_call_str += f"Making tool calls: **{tool_call.get('name')}**:\n\n"
                                tool_call_str += (
                                    f"**Arguments**: {tool_call.get('args')}\n\n"
                                )

                            yield {
                                "response_type": "text",
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": tool_call_str,
                            }
                elif step == "tools":
                    if self.debug:
                        print("Debug Event: ", data)
                    if "messages" in data:
                        # Take out the last Tool Message
                        tool_msg = data["messages"][-1]
                        if tool_msg.content:
                            if not _should_emit_tool_response(
                                tool_msg.name, tool_msg.content
                            ):
                                continue
                            content = f"**Tool {tool_msg.name} responded**: {tool_msg.content}\n"
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
                                "content": f"Tool call {tool_msg.name} has no content return or failed. check logs.",
                            }

    def _build_runnable_config(
        self,
        context_id: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        configurable = {"thread_id": context_id}

        if user_id is not None:
            configurable["actor_id"] = user_id
        if metadata is not None:
            configurable["metadata"] = metadata

        return {"configurable": configurable}
