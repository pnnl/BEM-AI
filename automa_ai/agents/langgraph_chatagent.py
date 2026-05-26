import asyncio
import atexit
import json
import logging
from typing import Dict, AsyncIterable, Any, List, Callable, Awaitable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, ToolMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from pydantic import BaseModel

from automa_ai.agents.remote_agent import (
    SubAgentSpec,
    make_subagent_tool,
    build_subagent_delegation_instruction,
    StreamEvent,
    set_subagent_context_id,
    reset_subagent_context_id,
    set_subagent_emitter,
    reset_subagent_emitter,
)
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.message_accumulator import AIMessageAccumulator
from automa_ai.common.network_retry import (
    compute_retry_delay,
    is_retryable_network_error,
)
from automa_ai.common.response_parser import extract_and_parse_json
from automa_ai.common.utils import map_server_config_to_mcp_connection
from automa_ai.retrieval.base import BaseRetriever
from automa_ai.common.types import ServerConfig
from automa_ai.memory.manager import DefaultMemoryManager, MemoryWriteEvent
from automa_ai.memory.memory_types import MemoryEntry, MemoryType
from automa_ai.prompts.prompt_template import RESPONSE_PROMPT
from automa_ai.skills import SkillManager
from automa_ai.skills.tools import build_load_skill_tool
from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.config.tools import ToolSpec
from automa_ai.tools import build_langchain_tools
from automa_ai.blackboard.store import BlackboardStore
from automa_ai.blackboard.tools import build_blackboard_tools
from automa_ai.config.token_budget import TokenBudgetConfig
from automa_ai.telemetry import build_telemetry, wrap_langchain_tool
from automa_ai.telemetry.context import (
    current_trace_id,
    reset_trace_context,
    set_trace_context,
)
from automa_ai.token_management import (
    TokenBudgetExceededError,
    TokenUsageStore,
    build_token_budget_middlewares,
)

logger = logging.getLogger(__name__)


def _should_emit_tool_response(tool_name: str | None, content: Any) -> bool:
    """Return whether a tool response should be streamed to the user."""
    if tool_name != "load_skill":
        return True
    return False


try:
    from langgraph_checkpoint_aws import AgentCoreMemorySaver
except ImportError:
    AgentCoreMemorySaver = None


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
        default_tools: list[ToolSpec] | None = None,
        checkpointer: Any | None = None,
        checkpointer_cleanup: Callable[[], None] | None = None,
        blackboard_store: BlackboardStore | None = None,
        blackboard_schema_name: str | None = None,
        blackboard_schema_version: str | None = None,
        blackboard_initial_data: dict | None = None,
        blackboard_contract: str | None = None,
        transient_retry_attempts: int = 0,
        budget_config: TokenBudgetConfig | None = None,
        token_usage_store: TokenUsageStore | None = None,
        telemetry_config: TelemetryConfig | dict[str, Any] | str | None = None,
        debug: bool = False,
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
        self.default_tool_specs = default_tools
        self.checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        self._checkpointer_cleanup = checkpointer_cleanup
        self._checkpointer_closed = False
        self.blackboard_store = blackboard_store
        self.blackboard_schema_name = blackboard_schema_name
        self.blackboard_schema_version = blackboard_schema_version
        self.blackboard_initial_data = blackboard_initial_data or {}
        self.blackboard_contract = blackboard_contract
        self.transient_retry_attempts = max(0, transient_retry_attempts)
        self.budget_config = budget_config
        self.token_usage_store = token_usage_store
        self.telemetry = build_telemetry(
            telemetry_config,
            base_attributes={
                "agent.name": agent_name,
                "agent.description": description,
                "agent.runtime": "langgraph_chat",
            },
        )
        self.debug = debug
        self.subagents = subagents

        # register close mechanism when shutdown if checkpointer has a cleanup function.
        if self._checkpointer_cleanup is not None:
            atexit.register(self.close)

        # Memory queue - object scope
        self._memory_write_queue: asyncio.Queue = asyncio.Queue()
        self._memory_writer_task: asyncio.Task | None = None

    def _checkpoint_thread_id(self, session_id: str) -> str:
        if AgentCoreMemorySaver is not None and isinstance(self.checkpointer, AgentCoreMemorySaver):
            return session_id
        return f"{self.agent_name}:{session_id}"

    def close(self) -> None:
        # Close agent behavior.
        # checkpointer close.
        if self._checkpointer_closed:
            return
        if self._checkpointer_cleanup is not None:
            try:
                self._checkpointer_cleanup()
            except Exception:
                logger.exception("Failed to close checkpointer cleanly.")
        self._checkpointer_closed = True

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
                    server_name: map_server_config_to_mcp_connection(
                        self.mcp_servers[server_name]
                    )
                    for server_name in self.mcp_servers
                }
            )

        tools = []
        used_tool_name = []
        if self.client:
            tools = [
                wrap_langchain_tool(tool, self.telemetry, source_type="mcp")
                for tool in await self.client.get_tools()
            ]
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
                tools.append(
                    wrap_langchain_tool(
                        make_subagent_tool(
                            subagent,
                            emitter,
                            self.blackboard_contract,
                        ),
                        self.telemetry,
                        source_type="subagent",
                    )
                )
            # build up the instruction
            self.instructions = (
                f"{self.instructions}\n\n"
                f"{build_subagent_delegation_instruction(self.subagents)}"
            )

        default_tools = build_langchain_tools(self.default_tool_specs, logger=logger)
        for tool in default_tools:
            if tool.name in used_tool_name:
                raise ValueError(f"Duplicate tool name '{tool.name}' detected.")
            used_tool_name.append(tool.name)
            tools.append(
                wrap_langchain_tool(tool, self.telemetry, source_type="binding")
            )

        if self.blackboard_store:
            for tool in build_blackboard_tools(self.blackboard_store):
                if tool.name in used_tool_name:
                    raise ValueError(f"Duplicate tool name '{tool.name}' detected.")
                used_tool_name.append(tool.name)
                tools.append(
                    wrap_langchain_tool(
                        tool,
                        self.telemetry,
                        source_type="blackboard",
                    )
                )
            if self.blackboard_contract:
                self.instructions = f"{self.instructions}\n\n{self.blackboard_contract}"

        if self.skill_manager and self.skill_manager.enabled:
            if "load_skill" in used_tool_name:
                raise ValueError("Duplicate tool name 'load_skill' detected.")
            used_tool_name.append("load_skill")
            tools.append(
                wrap_langchain_tool(
                    build_load_skill_tool(self.skill_manager),
                    self.telemetry,
                    source_type="skill",
                )
            )
            self.instructions = (
                f"{self.instructions}\n\n"
                "You can load specialized skills using the load_skill tool."
            )

        # process the instructions
        # step 1: add final response instruction
        self.instructions = f"{self.instructions}\n\n" f"{RESPONSE_PROMPT}"

        self.graph = create_agent(
            self.model,
            checkpointer=self.checkpointer,
            system_prompt=self.instructions,
            response_format=self.response_format,
            tools=tools,
            middleware=build_token_budget_middlewares(
                budget=self.budget_config,
                usage_store=self.token_usage_store,
                model=self.model,
                agent_name=self.agent_name,
            ),
        )

    def _ensure_blackboard(self, session_id: str) -> None:
        if not self.blackboard_store:
            return
        if not self.blackboard_schema_name or not self.blackboard_schema_version:
            raise ValueError(
                "Blackboard schema_name and schema_version are required when blackboard is enabled."
            )
        self.blackboard_store.get_or_create(
            session_id=session_id,
            schema_name=self.blackboard_schema_name,
            schema_version=self.blackboard_schema_version,
            initial_data=self.blackboard_initial_data,
        )

    def _activate_incoming_telemetry_context(
        self, metadata: dict[str, Any] | None
    ) -> Any | None:
        """Adopt trace ids forwarded by an upstream A2A caller.

        Local root calls create their own trace when `agent.turn` starts. A
        subagent call arrives with trace metadata, so this installs that context
        before the local span starts and returns the reset token for cleanup.
        """
        if not self.telemetry.enabled or current_trace_id() is not None:
            return None
        if not metadata:
            return None
        trace_id = metadata.get("telemetry_trace_id") or metadata.get("trace_id")
        if not trace_id:
            return None
        parent_span_id = metadata.get("telemetry_parent_span_id") or metadata.get(
            "span_id"
        )
        return set_trace_context(trace_id=str(trace_id), span_id=parent_span_id)

    def _agent_turn_attributes(
        self,
        *,
        context_id: str,
        task_id: str | None,
        user_id: str | None,
        mode: str,
    ) -> dict[str, Any]:
        """Build the common attributes every agent-turn span should carry."""
        attributes = {
            "agent.name": self.agent_name,
            "agent.runtime": "langgraph_chat",
            "agent.mode": mode,
            "session.id": context_id,
        }
        if task_id is not None:
            attributes["task.id"] = task_id
        if user_id is not None:
            attributes["user.id"] = user_id
        return attributes

    @staticmethod
    def _event_identity_attributes(
        *,
        session_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Return event identity attributes without null optional ids."""
        attributes = {"session.id": session_id}
        if task_id is not None:
            attributes["task.id"] = task_id
        if user_id is not None:
            attributes["user.id"] = user_id
        return attributes

    async def invoke(
        self,
        query,
        context_id,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        config = self._build_runnable_config(context_id, user_id, task_id)
        # queue for tool/subagent streaming
        subagent_event_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()

        async def emit_subagent_event(e: StreamEvent):
            """
            Called by tools / subagents to stream intermediate output.
            Must be non-blocking.
            """
            await subagent_event_queue.put(e)

        self._ensure_blackboard(context_id)
        if not self.graph:
            await self.init_graph(emit_subagent_event)
        telemetry_token = self._activate_incoming_telemetry_context(metadata)
        try:
            async with self.telemetry.span(
                "agent.turn",
                kind="server",
                attributes=self._agent_turn_attributes(
                    context_id=context_id,
                    task_id=task_id,
                    user_id=user_id,
                    mode="invoke",
                ),
            ):
                self.telemetry.event(
                    "message",
                    attributes={
                        "message.role": "user",
                        "message.content": query,
                        **self._event_identity_attributes(
                            session_id=context_id,
                            task_id=task_id,
                        ),
                    }
                )
                context_token = set_subagent_context_id(context_id)
                emitter_token = set_subagent_emitter(emit_subagent_event)
                try:
                    response = await self.graph.ainvoke(
                        {"messages": [("user", query)]}, config
                    )
                    self.telemetry.event(
                        "agent.response",
                        attributes={
                            "response.type": type(response).__name__,
                            **self._event_identity_attributes(
                                session_id=context_id,
                                task_id=task_id,
                            ),
                        },
                    )
                finally:
                    reset_subagent_emitter(emitter_token)
                    reset_subagent_context_id(context_token)
        finally:
            if telemetry_token is not None:
                reset_trace_context(telemetry_token)
        return response

    async def stream(
        self,
        query,
        context_id,
        task_id,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterable[dict[str, Any]]:
        metadata = metadata or {}
        telemetry_token = self._activate_incoming_telemetry_context(metadata)
        span_scope = self.telemetry.span(
            "agent.turn",
            kind="server",
            attributes=self._agent_turn_attributes(
                context_id=context_id,
                task_id=task_id,
                user_id=user_id,
                mode="stream",
            ),
        )
        span_entered = False
        span_closed = False

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

        try:
            span_scope.__enter__()
            span_entered = True
            self.telemetry.event(
                "message",
                attributes={
                    "message.role": "user",
                    "message.content": query,
                    **self._event_identity_attributes(
                        session_id=context_id,
                        task_id=task_id,
                    ),
                },
            )
            inputs = await self._build_stream_inputs(
                query, context_id, task_id, user_id, metadata
            )

            config = self._build_runnable_config(context_id, user_id, task_id)
            logger.info(
                f"Running planner agent stream for session {context_id} {task_id} with input {query}"
            )
            self._ensure_blackboard(context_id)
            if not self.graph:
                await self.init_graph(emit_subagent_event)
        except BaseException as exc:
            try:
                if span_entered:
                    span_scope.__exit__(type(exc), exc, exc.__traceback__)
                    span_closed = True
            finally:
                if telemetry_token is not None:
                    reset_trace_context(telemetry_token)
            raise

        # seen_messages = set()
        # Collect all streaming messages first
        # At the start of the stream
        async def agent_chunk_forwarder():
            """Forward agent chunks to output queue"""
            retry_count = 0
            try:
                while True:
                    message_accumulator = AIMessageAccumulator()
                    last_stream_text: str | None = None
                    emitted_output = False
                    tool_activity_started = False
                    human_message_queued = False
                    context_token = set_subagent_context_id(context_id)
                    emitter_token = set_subagent_emitter(emit_subagent_event)
                    try:
                        async for chunk in self.graph.astream(
                            inputs, config, stream_mode="messages"
                        ):
                            if self.debug:
                                print("Getting the chunk", chunk)
                            ck, meta = chunk

                            if isinstance(ck, HumanMessage) and self.memory_manager:
                                # Once the user turn is queued for persistence, do not
                                # replay the full stream on transient errors. A replay
                                # would enqueue the same human turn again and duplicate
                                # memory for this session. This is a local guard only;
                                # a future revisit should make memory persistence itself
                                # retry-safe/idempotent so transport retries are not
                                # coupled to memory side effects.
                                await self._memory_write_queue.put(
                                    MemoryWriteEvent(
                                        message=ck,
                                        session_id=context_id,
                                        task_id=task_id,
                                        user_id=user_id,
                                        metadata=metadata,
                                    )
                                )
                                human_message_queued = True

                            # Process agent chunk
                            if isinstance(ck, AIMessageChunk):
                                stream_text = message_accumulator.add_chunk(ck)
                                # Emit only text routed by the accumulator so
                                # artifact-marker content is withheld from
                                # status updates as soon as it is detected.
                                if stream_text and stream_text != last_stream_text:
                                    emitted_output = True
                                    await output_queue.put(
                                        {
                                            "response_type": "text",
                                            "is_task_complete": False,
                                            "require_user_input": False,
                                            "content": stream_text,
                                        }
                                    )
                                    last_stream_text = stream_text
                                if ck.tool_calls:
                                    tool_activity_started = True
                                    tool_call_str = ""
                                    for tool_call in ck.tool_calls:
                                        self.telemetry.event(
                                            "tool.requested",
                                            attributes={
                                                "tool.name": tool_call.get("name"),
                                                "tool.arguments": tool_call.get("args"),
                                                **self._event_identity_attributes(
                                                    session_id=context_id,
                                                    task_id=task_id,
                                                ),
                                            },
                                        )
                                        tool_call_str += f"Making tool calls: **{tool_call.get('name')}**:\n\n"
                                        tool_call_str += f"**Arguments**: {tool_call.get('args')}\n\n"

                                    emitted_output = True
                                    await output_queue.put(
                                        {
                                            "response_type": "text",
                                            "is_task_complete": False,
                                            "require_user_input": False,
                                            "content": tool_call_str,
                                        }
                                    )
                            elif isinstance(ck, ToolMessage):
                                tool_activity_started = True
                                self.telemetry.event(
                                    "tool.message",
                                    attributes={
                                        "tool.name": ck.name,
                                        "tool.result": ck.content,
                                        **self._event_identity_attributes(
                                            session_id=context_id,
                                            task_id=task_id,
                                        ),
                                    },
                                )
                                if ck.content:
                                    if not _should_emit_tool_response(
                                        ck.name, ck.content
                                    ):
                                        continue
                                    content = f"\n\n **Tool {ck.name} responded**: {ck.content}\n\n"
                                    emitted_output = True
                                    await output_queue.put(
                                        {
                                            "response_type": "text",
                                            "is_task_complete": False,
                                            "require_user_input": False,
                                            "content": content,
                                        }
                                    )
                                else:
                                    emitted_output = True
                                    await output_queue.put(
                                        {
                                            "response_type": "text",
                                            "is_task_complete": False,
                                            "require_user_input": False,
                                            "content": f"Tool call {ck.name} has no content return or failed. check logs.",
                                        }
                                    )

                        await self._emit_final_output(
                            output_queue=output_queue,
                            message_accumulator=message_accumulator,
                            session_id=context_id,
                            task_id=task_id,
                            user_id=user_id,
                            metadata=metadata,
                        )
                        break
                    except TokenBudgetExceededError as exc:
                        logger.info(
                            "Token budget stopped agent stream for %s "
                            "(session_id=%s, task_id=%s): %s",
                            self.agent_name,
                            context_id,
                            task_id,
                            exc,
                        )
                        await output_queue.put(self._token_budget_exceeded_output(exc))
                        break
                    except Exception as exc:
                        logger.exception(
                            "Agent stream failed for %s (session_id=%s, task_id=%s)",
                            self.agent_name,
                            context_id,
                            task_id,
                        )
                        should_retry = self._should_retry_stream_error(
                            exc=exc,
                            retry_count=retry_count,
                            emitted_output=emitted_output,
                            tool_activity_started=tool_activity_started,
                            human_message_queued=human_message_queued,
                        )
                        if should_retry:
                            retry_count += 1
                            delay = compute_retry_delay(retry_count)
                            logger.warning(
                                "Retrying agent stream for %s after transient error "
                                "(attempt %s/%s).",
                                self.agent_name,
                                retry_count,
                                self.transient_retry_attempts,
                            )
                            if delay > 0:
                                await asyncio.sleep(delay)
                            continue

                        error_content = "I ran into an internal error while processing the request. Please try again."
                        if self.debug:
                            error_content = (
                                "Agent runtime error while processing the request: "
                                f"{type(exc).__name__}: {exc}"
                            )
                        await output_queue.put(
                            {
                                "response_type": "text",
                                "is_task_complete": True,
                                "require_user_input": False,
                                "content": error_content,
                            }
                        )
                        break
                    finally:
                        reset_subagent_emitter(emitter_token)
                        reset_subagent_context_id(context_token)
            except TokenBudgetExceededError as exc:
                logger.info(
                    "Token budget stopped agent stream forwarder for %s: %s",
                    self.agent_name,
                    exc,
                )
                await output_queue.put(self._token_budget_exceeded_output(exc))
            except Exception as exc:
                logger.exception(
                    "Agent stream forwarder failed for %s", self.agent_name
                )
                error_content = "I ran into an internal error while processing the request. Please try again."
                if self.debug:
                    error_content = f"Agent runtime error while processing the request: {type(exc).__name__}: {exc}"
                await output_queue.put(
                    {
                        "response_type": "text",
                        "is_task_complete": True,
                        "require_user_input": False,
                        "content": error_content,
                    }
                )
            finally:
                await output_queue.put(None)

        if self.memory_manager:
            self._memory_writer_task = asyncio.create_task(self._start_memory_writer())
        # Start both forwarders
        forwarder_tasks = [
            asyncio.create_task(
                self._forward_subagent_events(subagent_event_queue, output_queue)
            ),
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
        except BaseException as exc:
            span_scope.__exit__(type(exc), exc, exc.__traceback__)
            span_closed = True
            raise
        finally:
            for task in forwarder_tasks:
                task.cancel()
            # Signal memory writer shutdown and await completion
            if self.memory_manager:
                await self._memory_write_queue.put(None)
                if self._memory_writer_task:
                    await self._memory_writer_task
            try:
                if not span_closed:
                    span_scope.__exit__(None, None, None)
            finally:
                if telemetry_token is not None:
                    reset_trace_context(telemetry_token)

    async def _start_memory_writer(self):
        """Background task that writes memory entries without blocking the forwarder."""
        while True:
            event: MemoryWriteEvent = await self._memory_write_queue.get()
            if event is None:  # Shutdown signal
                break
            try:
                # Write to short-term store
                await self.memory_manager.add_memory(
                    event.message,
                    session_id=event.session_id,
                    task_id=event.task_id,
                    user_id=event.user_id,
                    metadata=event.metadata,
                    memory_type=MemoryType.SHORT_TERM,
                )
                asyncio.create_task(self.memory_manager.manage_memory_size())
            except Exception as e:
                logger.exception("Memory manager failed")

    async def _build_stream_inputs(
        self,
        query: str,
        context_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = ""
        if self.retriever:
            context = await self.retriever.asimilarity_search(query)

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

        memory_additional_system_query = await self._build_memory_context(
            query,
            context_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
        )

        if memory_additional_system_query.strip():
            additional_system_query = (
                f"{additional_system_query}\n\n{memory_additional_system_query}"
            )

        messages = [{"role": "user", "content": query}]
        if additional_system_query.strip():
            messages.insert(0, {"role": "system", "content": additional_system_query})
        inputs = {"messages": messages}

        logger.debug("Inputs to the LLM: %s", inputs)
        return inputs

    async def _forward_subagent_events(
        self,
        subagent_event_queue: asyncio.Queue[StreamEvent],
        output_queue: asyncio.Queue,
    ) -> None:
        while True:
            try:
                e = await subagent_event_queue.get()
                content_str = self._format_subagent_event(e)
                self.telemetry.event(
                    "subagent.stream_event",
                    attributes={
                        "subagent.source": e.source,
                        "subagent.event_type": e.type,
                        "subagent.content": e.content,
                        # Serialize arbitrary metadata so the sanitizer treats
                        # it as one payload and stores only hash/length by
                        # default, instead of preserving nested secret fields.
                        "subagent.metadata_payload": json.dumps(
                            e.metadata or {},
                            default=str,
                            sort_keys=True,
                        ),
                    },
                )
                await output_queue.put(
                    {
                        "response_type": "text",
                        "is_task_complete": False,
                        "require_user_input": False,
                        "content": content_str,
                    }
                )
            except Exception as e:
                print(f"Error forwarding subagent event: {e}")
                break

    @staticmethod
    def _format_subagent_event(event: StreamEvent) -> str:
        # content_str = f"\n\n[{event.source}] "
        content_str = ""
        if event.metadata and event.metadata.get("final"):
            content_str += "(final) "
        if isinstance(event.content, (dict, list)):
            content_str += json.dumps(event.content)
        else:
            content_str += str(event.content)
        return content_str

    def _should_retry_stream_error(
        self,
        *,
        exc: Exception,
        retry_count: int,
        emitted_output: bool,
        tool_activity_started: bool,
        human_message_queued: bool,
    ) -> bool:
        if retry_count >= self.transient_retry_attempts:
            return False
        if emitted_output or tool_activity_started or human_message_queued:
            return False
        return is_retryable_network_error(exc)

    @staticmethod
    def _token_budget_exceeded_output(exc: TokenBudgetExceededError) -> dict[str, Any]:
        """Convert budget exceptions into a user-facing stream event."""
        return {
            "response_type": "text",
            "is_task_complete": True,
            "require_user_input": False,
            "content": str(exc),
        }

    async def _build_memory_context(
        self,
        query: str,
        *,
        context_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Retrieve and format prior-conversation memory for the given query."""
        if not self.memory_manager:
            return ""

        memory_list = await self.memory_manager.retrieve_memories(
            query,
            session_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
            memory_types=[MemoryType.SHORT_TERM, MemoryType.LONG_TERM],
            include_short_term=True,
            include_long_term=True,
        )
        if not memory_list:
            return ""

        formatted = "\n".join(f"{m.timestamp}: {m.content}" for m in memory_list)
        section = (
            "You are also given the following context from past conversations "
            f"with the user:\n{formatted}"
        )
        if self.debug:
            logger.info("Retrieved memory context: %s", section)
        return section

    def _build_runnable_config(
        self,
        context_id: str,
        user_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            AgentCoreMemorySaver is not None
            and isinstance(self.checkpointer, AgentCoreMemorySaver)
            and user_id is None
        ):
            raise ValueError(
                "AgentCoreMemorySaver requires user_id to be set for proper namespacing of memory. "
                "Please provide a user_id when invoking the agent."
            )

        configurable = {
            "thread_id": self._checkpoint_thread_id(context_id),
            "automa_context_id": context_id,
        }

        if user_id is not None:
            configurable["actor_id"] = user_id
        if task_id is not None:
            configurable["task_id"] = task_id

        return {"configurable": configurable}

    async def _emit_final_output(
        self,
        output_queue: asyncio.Queue,
        message_accumulator: AIMessageAccumulator,
        session_id: str,
        task_id: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        final_text = message_accumulator.get_assistant_text()
        artifact_text = message_accumulator.get_artifact_text()
        self.telemetry.event(
            "message",
            attributes={
                "message.role": "assistant",
                "message.content": final_text,
                "artifact.content": artifact_text,
                **self._event_identity_attributes(
                    session_id=session_id,
                    task_id=task_id,
                    user_id=user_id,
                ),
            },
        )

        ai_message = message_accumulator.finalize()
        if self.memory_manager:
            await self._memory_write_queue.put(
                MemoryWriteEvent(
                    message=ai_message,
                    session_id=session_id,
                    task_id=task_id,
                    user_id=user_id,
                    metadata=metadata,
                )
            )
        if artifact_text:
            try:
                _, parsed = extract_and_parse_json(artifact_text)
                if isinstance(parsed, dict):
                    additional_artifacts = []
                    if final_text:
                        additional_artifacts.append(
                            {
                                "response_type": "text",
                                "content": final_text,
                                "artifact_name": f"{self.agent_name}-summary",
                            }
                        )
                    await output_queue.put(
                        {
                            "response_type": "data",
                            "is_task_complete": True,
                            "require_user_input": False,
                            "content": parsed,
                            "additional_artifacts": additional_artifacts,
                        }
                    )
                    return
            except Exception:
                # Intentionally pass.
                pass

        await output_queue.put(
            {
                "response_type": "text",
                "is_task_complete": True,
                "require_user_input": False,
                "content": final_text,
            }
        )
