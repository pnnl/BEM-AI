import asyncio
import logging
from typing import Dict, AsyncIterable, Any, List, Callable, Awaitable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, ToolMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from pydantic import BaseModel

from automa_ai.agents.remote_agent import SubAgentSpec, make_subagent_tool, build_subagent_delegation_instruction, \
    StreamEvent
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.message_accumulator import AIMessageAccumulator
from automa_ai.common.response_parser import extract_and_parse_json
from automa_ai.common.retriever import BaseRetriever
from automa_ai.common.types import ServerConfig
from automa_ai.memory.manager import DefaultMemoryManager, MemoryWriteEvent
from automa_ai.memory.memory_types import MemoryType
from automa_ai.metrics.collector import MetricsCollector
from automa_ai.metrics.extractor import extract_metrics_from_chunk
from automa_ai.prompt_engineering.prompt_template import RESPONSE_PROMPT
from automa_ai.skills import SkillManager
from automa_ai.skills.active_skill import ActiveSkillState, format_active_skill_message
from automa_ai.skills.tools import build_load_skill_tool

memory = MemorySaver()

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
        subagents: List[SubAgentSpec] | None = None,
        skills_manager: SkillManager | None = None,
        memory_manager: DefaultMemoryManager = None,
        enable_metrics: bool = False,
        debug: bool = False
    ):

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
        self.memory_manager = memory_manager
        self.skill_manager = skills_manager
        self.metrics = None
        self.debug = debug
        if enable_metrics:
            self.metrics = MetricsCollector()
        self.subagents = subagents
        self._active_skill_state = ActiveSkillState()

        # Memory queue - object scope
        self._memory_write_queue: asyncio.Queue = asyncio.Queue()
        self._memory_writer_task: asyncio.Task | None = None

    async def init_graph(self, emitter: Callable[[StreamEvent], Awaitable[None]]):
        """Load the agent graph
        emitter: agent internal event queue for streaming, a separate streaming channel from langchain's streaming.
        """
        logger.info(f"Initializing {self.agent_name} metadata")
        if self.mcp_servers:
            # Loading mcp server clients.
            logger.info(f"Subscribe to MCPs through sse")

            self.client = MultiServerMCPClient(
                {
                    server_name: {
                        "url": f"{self.mcp_servers[server_name].url}/sse" if self.mcp_servers[server_name].transport == "sse" else f"{self.mcp_servers[server_name].url}/mcp",
                        "transport": self.mcp_servers[server_name].transport,
                    }
                    for server_name in self.mcp_servers
                }
            )

        tools = []
        used_tool_name = []
        if self.client:
            tools = await self.client.get_tools()
            for tool in tools:
                if self.debug:
                    print(self.agent_name, f"Loaded tools {tool.name}")
                used_tool_name.append(tool.name)
                logger.info(f"Loaded tools {tool.name}")


        if self.subagents:
            for subagent in self.subagents:
                base = subagent.tool_name

                if base in used_tool_name:
                    raise ValueError(
                        f"Duplicate name '{base}'"
                        f"derived from agent '{subagent.name}'"
                        "Rename the agent to avoid duplicate names"
                    )
                used_tool_name.append(base)
                tools.append(make_subagent_tool(subagent, emitter))
            # build up the instruction
            self.instructions = (
                f"{self.instructions}\n\n"
                f"{build_subagent_delegation_instruction(self.subagents)}"
            )

        if self.skill_manager and self.skill_manager.enabled:
            if "load_skill" in used_tool_name:
                raise ValueError("Duplicate tool name 'load_skill' detected.")
            used_tool_name.append("load_skill")
            tools.append(build_load_skill_tool(self.skill_manager))
            self.instructions = (
                f"{self.instructions}\n\n"
                "You can load specialized skills using the load_skill tool."
            )

        # process the instructions
        # step 1: add final response instruction
        self.instructions = (
            f"{self.instructions}\n\n"
            f"{RESPONSE_PROMPT}"
        )

        self.graph = create_agent(
            self.model,
            checkpointer=memory,
            system_prompt=self.instructions,
            response_format=self.response_format,
            tools=tools
        )

    def _clear_active_skill_if_requested(self) -> None:
        if self._active_skill_state.clear_active_skill_next_turn:
            self._active_skill_state.clear()

    def clear_active_skill(self) -> None:
        """Clear any active skill and re-enable skill loading next turn."""
        self._active_skill_state.clear()

    def request_clear_active_skill(self) -> None:
        """Schedule the active skill to be cleared at the start of the next turn."""
        self._active_skill_state.clear_active_skill_next_turn = True

    async def invoke(self, query, session_id: str) -> Any:
        config = {"configurable": {"thread_id": session_id}}
        # queue for tool/subagent streaming
        subagent_event_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        async def emit_subagent_event(e: StreamEvent):
            """
            Called by tools / subagents to stream intermediate output.
            Must be non-blocking.
            """
            await subagent_event_queue.put(e)

        if not self.graph:
            await self.init_graph(emit_subagent_event)
        self._clear_active_skill_if_requested()
        inputs = await self._build_stream_inputs(query, session_id)
        response = await self.graph.ainvoke(inputs, config)
        self._capture_skill_tool_outputs(response)
        return response

    async def stream(self, query, session_id, task_id) -> AsyncIterable[dict[str, Any]]:
        # queue for tool/subagent streaming
        subagent_event_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        # queue for agent streaming
        output_queue: asyncio.Queue = asyncio.Queue()

        ### Subagent emit event
        async def emit_subagent_event(e: StreamEvent) -> None:
            """
            Called by tools / subagents to stream intermediate output.
            Must be non-blocking.
            """
            await subagent_event_queue.put(e)

        # If selected to track metrics
        if self.metrics:
            if self.metrics.current_query_id and self.metrics.current_query_id != query:
                # If a new task, write out the previous task.
                print(self.metrics.summary_for_query(self.metrics.current_query_id))
            self.metrics.start_query(task_id)
        if not self.graph:
            await self.init_graph(emit_subagent_event)
        self._clear_active_skill_if_requested()
        inputs = await self._build_stream_inputs(query, session_id)
        config = {"configurable": {"thread_id": session_id}}
        logger.info(
            f"Running planner agent stream for session {session_id} {task_id} with input {query}"
        )
        # seen_messages = set()
        # Collect all streaming messages first
        # At the start of the stream
        async def agent_chunk_forwarder():
            message_accumulator = AIMessageAccumulator()
            """Forward agent chunks to output queue"""
            # use to track the tool call steps
            active_tool_calls = 0
            try:
                async for chunk in self.graph.astream(inputs, config, stream_mode="messages"):
                    if self.debug:
                        print("Getting the chunk", chunk)
                    ck, meta = chunk

                    if isinstance(ck, HumanMessage) and self.memory_manager:
                        # Enqueue human message for memory
                        await self._memory_write_queue.put(MemoryWriteEvent(message=ck, session_id=session_id, user_id=task_id))

                    # Process agent chunk
                    if isinstance(ck, AIMessageChunk):
                        if self.metrics:
                            # Record tracking
                            if ck.response_metadata:
                                self.metrics.add(extract_metrics_from_chunk(
                                    ck,
                                    session_id=session_id,
                                    query_id=self.metrics.current_query_id
                                ))
                        # accumulate ai messages
                        message_accumulator.add_chunk(ck)

                        # is task completed?
                        is_last_model_step = (
                                ck.chunk_position
                                and ck.chunk_position == "last"
                                and active_tool_calls == 0
                        )

                        if ck.content:
                            content = self._normalize_chunk_content(ck)
                            if content is not None:
                                if is_last_model_step:
                                    await self._emit_final_output(
                                        output_queue,
                                        message_accumulator,
                                        session_id,
                                        task_id,
                                    )
                                else:
                                    # not last step, continue streaming
                                    await output_queue.put({
                                        "response_type": "text",
                                        "is_task_complete": False,
                                        "require_user_input": False,
                                        "content": message_accumulator.get_last_assistant_text(),
                                    })

                        elif ck.tool_calls:
                            active_tool_calls += len(ck.tool_calls)
                            tool_call_str = ""
                            for tool_call in ck.tool_calls:
                                if tool_call.get("name") == "load_skill":
                                    args = tool_call.get("args") or {}
                                    if isinstance(args, dict):
                                        self._active_skill_state.pending_skill_name = args.get("skill_name")
                                tool_call_str += f"Making tool calls: **{tool_call.get('name')}**:\n\n"
                                tool_call_str += f"**Arguments**: {tool_call.get('args')}\n\n"

                            await output_queue.put( {
                                "response_type": "text",
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": tool_call_str,
                            })
                        else:
                            if is_last_model_step:
                                await self._emit_final_output(
                                    output_queue,
                                    message_accumulator,
                                    session_id,
                                    task_id,
                                )
                            # continue
                    elif isinstance(ck, ToolMessage):
                        active_tool_calls -= 1
                        if ck.content:
                            if ck.name == "load_skill":
                                self._active_skill_state.mark_loaded(
                                    self._active_skill_state.pending_skill_name,
                                    ck.content,
                                )
                                continue
                            # stream_buffer.append(ck.content)
                            content = f"\n\n **Tool {ck.name} responded**: {ck.content}\n\n"
                            await output_queue.put( {
                                "response_type": "text",
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": content,
                            })
                        else:
                            # Fall back
                            await output_queue.put( {
                                "response_type": "text",
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": f"Tool call {ck.name} has no content return or failed. check logs.",
                            })
            finally:
                await output_queue.put(None)

        if self.memory_manager:
            self._memory_writer_task = asyncio.create_task(self._start_memory_writer())
        # Start both forwarders
        forwarder_tasks = [
            asyncio.create_task(self._forward_subagent_events(subagent_event_queue, output_queue)),
            asyncio.create_task(agent_chunk_forwarder()),
        ]

        try:
            # Yield from merged queue
            while True:
                item = await output_queue.get()
                if item is None:  # Agent finished
                    break
                # print(f"Yielding from {item.get('source')}: {item.get('content', '')[:50]}...")
                yield item
        finally:
            for task in forwarder_tasks:
                task.cancel()
            # Signal memory writer shutdown and await completion
            if self.memory_manager:
                await self._memory_write_queue.put(None)
                if self._memory_writer_task:
                    await self._memory_writer_task

    async def _start_memory_writer(self):
        """Background task that writes memory entries without blocking the forwarder."""
        while True:
            event = await self._memory_write_queue.get()
            if event is None:  # Shutdown signal
                break
            try:
                # Write to short-term store
                await self.memory_manager.add_memory(event.message, session_id=event.session_id, user_id=event.user_id)
                asyncio.create_task(self.memory_manager.manage_memory_size())
            except Exception as e:
                logger.exception("Memory manager failed")

    async def _build_stream_inputs(self, query: str, session_id: str) -> dict[str, Any]:
        context = ""
        if self.retriever:
            context = await self.retriever.asimilarity_search_by_vector(query)

        if context:
            additional_system_query = f"""
                You are given the following context from the knowledge base:
                {context}
            """
            if self.debug:
                print(additional_system_query)
                logger.info(f"Retrieved query: {additional_system_query}")
        else:
            additional_system_query = ""

        if self.memory_manager:
            memory_list = await self.memory_manager.retrieve_memories(
                query,
                session_id=session_id,
                memory_types=[MemoryType.SHORT_TERM, MemoryType.LONG_TERM],
                include_short_term=True,
                include_long_term=True,
            )
            if memory_list:
                formatted_memories = [f"{m.timestamp}: {m.content}" for m in memory_list]
                additional_system_query = f"""
                    {additional_system_query}

                    You are also given the following context from the past conversations with the user:
                    {formatted_memories}
                    """

        messages = []
        # Order: base system prompt (handled by graph), then active skill, then retrieved/memory context, then user.
        system_messages = []
        if self._active_skill_state.active_skill_text:
            system_messages.append(
                {
                    "role": "system",
                    "content": format_active_skill_message(
                        self._active_skill_state.active_skill_text
                    ),
                },
            )
        if additional_system_query.strip():
            system_messages.append(
                {"role": "system", "content": additional_system_query}
            )
        messages.extend(system_messages)
        messages.append({"role": "user", "content": query})
        inputs = {"messages": messages}

        logger.debug("Inputs to the LLM: %s", inputs)
        return inputs

    def _capture_skill_tool_outputs(self, response: dict[str, Any]) -> None:
        for message in response.get("messages", []):
            if isinstance(message, ToolMessage) and message.name == "load_skill":
                self._active_skill_state.mark_loaded(
                    self._active_skill_state.pending_skill_name,
                    message.content,
                )

    def _get_active_skill_text_for_testing(self) -> str | None:
        return self._active_skill_state.active_skill_text

    async def _forward_subagent_events(
        self,
        subagent_event_queue: asyncio.Queue[StreamEvent],
        output_queue: asyncio.Queue,
    ) -> None:
        while True:
            try:
                e = await subagent_event_queue.get()
                content_str = self._format_subagent_event(e)
                await output_queue.put({
                    "response_type": "text",
                    "is_task_complete": False,
                    "require_user_input": False,
                    "content": content_str,
                })
            except Exception as e:
                print(f"Error forwarding subagent event: {e}")
                break

    @staticmethod
    def _format_subagent_event(event: StreamEvent) -> str:
        #content_str = f"\n\n[{event.source}] "
        content_str = ""
        if event.metadata and event.metadata.get("final"):
            content_str += "(final) "
        content_str += event.content
        return content_str

    @staticmethod
    def _normalize_chunk_content(chunk: AIMessageChunk) -> str | None:
        content = chunk.content
        if content and isinstance(content, list):
            # likely this is a gemini responses
            content = content[0]
            if chunk.response_metadata and chunk.response_metadata.get("model_provider") in [
                "google_genai",
                "bedrock_converse",
            ]:
                # in this case, it is likely a json inside a list
                if content["type"] == "text" and content["text"]:
                    content = content["text"]
                elif content["type"] == "tool_use":
                    # seems unique to claude - temporary block tool call info first.
                    content = "-"
        return content

    async def _emit_final_output(
        self,
        output_queue: asyncio.Queue,
        message_accumulator: AIMessageAccumulator,
        session_id: str,
        task_id: str,
    ) -> None:
        final_text = message_accumulator.get_assistant_text()
        artifact_text = message_accumulator.get_artifact_text()

        ai_message = message_accumulator.finalize()
        if self.memory_manager:
            await self._memory_write_queue.put(
                MemoryWriteEvent(message=ai_message, session_id=session_id, user_id=task_id)
            )
        if artifact_text:
            try:
                _, parsed = extract_and_parse_json(artifact_text)
                if isinstance(parsed, dict):
                    await output_queue.put({
                        "response_type": "data",
                        "is_task_complete": True,
                        "require_user_input": False,
                        "content": parsed,
                    })
                    return
            except Exception:
                # Intentionally pass.
                pass

        await output_queue.put({
            "response_type": "text",
            "is_task_complete": True,
            "require_user_input": False,
            "content": final_text,
        })
