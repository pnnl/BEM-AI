import asyncio
import atexit
import json
import logging
from collections.abc import Mapping
from typing import Dict, AsyncIterable, Any, List, Callable, Awaitable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    ToolMessage,
    HumanMessage,
)
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
from automa_ai.memory.memory_types import MemoryType
from automa_ai.prompts.prompt_template import RESPONSE_PROMPT
from automa_ai.skills import SkillManager
from automa_ai.skills.tools import build_load_skill_tool
from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.config.tools import ToolSpec
from automa_ai.tools import build_langchain_tools
from automa_ai.tools.base import content_to_safe_text, infer_tool_result_provider
from automa_ai.blackboard.store import BlackboardStore
from automa_ai.blackboard.tools import build_blackboard_tools
from automa_ai.config.token_budget import TokenBudgetConfig
from automa_ai.hook import (
    ContextPipeline,
    HookRunner,
    InputAssembler,
    TurnInputBuilder,
    TurnInputs,
    TurnResult,
)
from automa_ai.telemetry import (
    AutomaLLMCallbackHandler,
    build_telemetry,
    wrap_langchain_tool,
)
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
        hook_runner: HookRunner | None = None,
        context_pipeline: ContextPipeline | None = None,
        input_assembler: InputAssembler | None = None,
        turn_input_builder: TurnInputBuilder | None = None,
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
        self._telemetry_closed = False
        self.blackboard_store = blackboard_store
        self.blackboard_schema_name = blackboard_schema_name
        self.blackboard_schema_version = blackboard_schema_version
        self.blackboard_initial_data = blackboard_initial_data or {}
        self.blackboard_contract = blackboard_contract
        self.transient_retry_attempts = max(0, transient_retry_attempts)
        self.budget_config = budget_config
        self.token_usage_store = token_usage_store
        self.turn_input_builder = turn_input_builder or TurnInputBuilder.default(
            retriever=retriever,
            memory_manager=memory_manager,
            hook_runner=hook_runner,
            context_pipeline=context_pipeline,
            input_assembler=input_assembler,
            logger=logger,
            debug=debug,
        )
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

        # Register close mechanisms for standalone scripts. A2AAgentServer also
        # calls aclose() during normal server teardown.
        if self._checkpointer_cleanup is not None or self.telemetry.enabled:
            atexit.register(self.close)

        # Memory queue - object scope
        self._memory_write_queue: asyncio.Queue = asyncio.Queue()
        self._memory_writer_task: asyncio.Task | None = None

    def _checkpoint_thread_id(self, session_id: str) -> str:
        if AgentCoreMemorySaver is not None and isinstance(
            self.checkpointer, AgentCoreMemorySaver
        ):
            return session_id
        return f"{self.agent_name}:{session_id}"

    def close(self) -> None:
        # Close agent behavior.
        self._close_checkpointer()
        self._close_telemetry()

    async def aclose(self) -> None:
        """Async-safe agent teardown for server shutdown paths."""
        self._close_checkpointer()
        await self._aclose_telemetry()

    def _close_checkpointer(self) -> None:
        if self._checkpointer_closed:
            return
        if self._checkpointer_cleanup is not None:
            try:
                self._checkpointer_cleanup()
            except Exception:
                logger.exception("Failed to close checkpointer cleanly.")
        self._checkpointer_closed = True

    def _close_telemetry(self) -> None:
        if self._telemetry_closed:
            return
        self.telemetry.close()
        self._telemetry_closed = True

    async def _aclose_telemetry(self) -> None:
        if self._telemetry_closed:
            return
        await self.telemetry.aflush()
        await self.telemetry.aclose()
        self._telemetry_closed = True

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

        default_tools = build_langchain_tools(
            self.default_tool_specs,
            logger=logger,
            model_provider=infer_tool_result_provider(self.model),
        )
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

    async def _emit_context_provider_error(
        self,
        provider: Any,
        error: Exception,
        turn: Any,
    ) -> None:
        """Record degraded context-provider failures in telemetry."""
        self.telemetry.event(
            "context_provider.failed",
            attributes={
                "context.provider": provider.__class__.__name__,
                "exception.type": type(error).__name__,
                "exception.message": str(error),
                **self._event_identity_attributes(
                    session_id=turn.context_id,
                    task_id=turn.task_id,
                    user_id=turn.user_id,
                ),
            },
        )

    async def invoke(
        self,
        query,
        context_id,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        metadata = metadata or {}
        # queue for tool/subagent streaming
        subagent_event_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()

        async def emit_subagent_event(e: StreamEvent):
            """
            Called by tools / subagents to stream intermediate output.
            Must be non-blocking.
            """
            await subagent_event_queue.put(e)

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
                self._ensure_blackboard(context_id)
                if not self.graph:
                    await self.init_graph(emit_subagent_event)
                turn_inputs = await self.turn_input_builder.build_inputs(
                    query=query,
                    context_id=context_id,
                    task_id=task_id,
                    user_id=user_id,
                    metadata=metadata,
                    context_error_handler=self._emit_context_provider_error,
                )
                turn = turn_inputs.turn
                inputs = turn_inputs.inputs
                config = self._build_runnable_config(
                    turn.context_id,
                    turn.user_id,
                    turn.task_id,
                    metadata=metadata,
                )
                self.telemetry.event(
                    "message",
                    attributes={
                        "message.role": "user",
                        "message.content": turn.query,
                        **self._attachment_telemetry_attributes(
                            turn.attachments
                        ),
                        **self._event_identity_attributes(
                            session_id=turn.context_id,
                            task_id=turn.task_id,
                            user_id=turn.user_id,
                        ),
                    },
                )
                context_token = set_subagent_context_id(turn.context_id)
                emitter_token = set_subagent_emitter(emit_subagent_event)
                try:
                    response = await self.graph.ainvoke(inputs, config)
                    await self.turn_input_builder.after_turn(
                        turn,
                        self._build_invoke_turn_result(response, turn_inputs),
                    )
                    self._emit_model_usage_telemetry(
                        self._response_messages(response),
                        session_id=turn.context_id,
                        task_id=turn.task_id,
                        user_id=turn.user_id,
                    )
                    self.telemetry.event(
                        "agent.response",
                        attributes={
                            "response.type": type(response).__name__,
                            **self._event_identity_attributes(
                                session_id=turn.context_id,
                                task_id=turn.task_id,
                                user_id=turn.user_id,
                            ),
                        },
                    )
                except Exception as exc:
                    await self.turn_input_builder.on_turn_error(turn, exc)
                    raise
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
        # agent_chunk_forwarder owns the accumulator, but after_turn runs in the
        # outer generator after all chunks have been yielded. A Future hands over
        # only the compact final result instead of buffering streamed chunks.
        stream_result: asyncio.Future[TurnResult] = asyncio.Future()
        turn = None

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
            self._ensure_blackboard(context_id)
            if not self.graph:
                await self.init_graph(emit_subagent_event)
            turn_inputs = await self.turn_input_builder.build_inputs(
                query=query,
                context_id=context_id,
                task_id=task_id,
                user_id=user_id,
                metadata=metadata,
                context_error_handler=self._emit_context_provider_error,
            )
            turn = turn_inputs.turn
            inputs = turn_inputs.inputs
            turn_degraded = turn_inputs.degraded
            missing_providers = turn_inputs.missing_providers
            context_id = turn.context_id
            task_id = turn.task_id
            user_id = turn.user_id
            metadata = turn.metadata
            self.telemetry.event(
                "message",
                attributes={
                    "message.role": "user",
                    "message.content": turn.query,
                    **self._attachment_telemetry_attributes(turn.attachments),
                    **self._event_identity_attributes(
                        session_id=turn.context_id,
                        task_id=turn.task_id,
                        user_id=turn.user_id,
                    ),
                },
            )

            config = self._build_runnable_config(
                turn.context_id,
                turn.user_id,
                turn.task_id,
                metadata=metadata
            )
            logger.info(
                "Running planner agent stream for session %s %s with input %s",
                turn.context_id,
                turn.task_id,
                turn.query,
            )
        except BaseException as exc:
            if turn is not None and isinstance(exc, Exception):
                await self.turn_input_builder.on_turn_error(turn, exc)
            try:
                if span_entered:
                    try:
                        span_scope.__exit__(type(exc), exc, exc.__traceback__)
                    finally:
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
                                                    user_id=user_id,
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
                                            user_id=user_id,
                                        ),
                                    },
                                )
                                if ck.content:
                                    if not _should_emit_tool_response(
                                        ck.name, ck.content
                                    ):
                                        continue
                                    safe_content = content_to_safe_text(ck.content)
                                    content = (
                                        f"\n\n **Tool {ck.name} responded**: "
                                        f"{safe_content}\n\n"
                                    )
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
                            degraded=turn_degraded,
                            missing_providers=missing_providers,
                            stream_result=stream_result,
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
                        output = self._token_budget_exceeded_output(exc)
                        if not stream_result.done():
                            stream_result.set_result(
                                TurnResult(
                                    mode="stream",
                                    content=output["content"],
                                    final_output=output,
                                    status="token_budget_exceeded",
                                    degraded=turn_degraded,
                                    missing_providers=missing_providers,
                                )
                            )
                        await output_queue.put(output)
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
                        output = {
                            "response_type": "text",
                            "is_task_complete": True,
                            "require_user_input": False,
                            "content": error_content,
                        }
                        if not stream_result.done():
                            stream_result.set_result(
                                TurnResult(
                                    mode="stream",
                                    content=error_content,
                                    final_output=output,
                                    status="error",
                                    degraded=turn_degraded,
                                    missing_providers=missing_providers,
                                )
                            )
                        await output_queue.put(output)
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
                output = self._token_budget_exceeded_output(exc)
                if not stream_result.done():
                    stream_result.set_result(
                        TurnResult(
                            mode="stream",
                            content=output["content"],
                            final_output=output,
                            status="token_budget_exceeded",
                            degraded=turn_degraded,
                            missing_providers=missing_providers,
                        )
                    )
                await output_queue.put(output)
            except Exception as exc:
                logger.exception(
                    "Agent stream forwarder failed for %s", self.agent_name
                )
                error_content = "I ran into an internal error while processing the request. Please try again."
                if self.debug:
                    error_content = f"Agent runtime error while processing the request: {type(exc).__name__}: {exc}"
                output = {
                    "response_type": "text",
                    "is_task_complete": True,
                    "require_user_input": False,
                    "content": error_content,
                }
                if not stream_result.done():
                    stream_result.set_result(
                        TurnResult(
                            mode="stream",
                            content=error_content,
                            final_output=output,
                            status="error",
                            degraded=turn_degraded,
                            missing_providers=missing_providers,
                        )
                    )
                await output_queue.put(output)
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
            if turn is not None:
                if stream_result.done():
                    await self.turn_input_builder.after_turn(
                        turn,
                        stream_result.result(),
                    )
                else:
                    # The forwarder can exit via BaseException, such as
                    # cancellation from graph.astream(), before it can produce
                    # a final result. Do not fabricate a successful TurnResult.
                    self.telemetry.event(
                        "stream.incomplete",
                        attributes=self._event_identity_attributes(
                            session_id=context_id,
                            task_id=task_id,
                            user_id=user_id,
                        ),
                    )
        except BaseException as exc:
            if turn is not None and isinstance(exc, Exception):
                await self.turn_input_builder.on_turn_error(turn, exc)
            try:
                if isinstance(exc, GeneratorExit):
                    # GeneratorExit fires when the caller stops iterating (e.g.
                    # the A2A executor breaks after the final item).  The agent
                    # itself may have finished cleanly and already resolved
                    # stream_result.  Fire after_turn so hooks and session
                    # persistence see every completed turn, not only turns whose
                    # consumer happened to drain the queue past the None sentinel.
                    if turn is not None and stream_result.done():
                        await self.turn_input_builder.after_turn(
                            turn,
                            stream_result.result(),
                        )
                    self.telemetry.event(
                        "stream.closed",
                        attributes={
                            "stream.close.reason": "generator_exit",
                            **self._event_identity_attributes(
                                session_id=context_id,
                                task_id=task_id,
                                user_id=user_id,
                            ),
                        },
                    )
                    span_scope.__exit__(None, None, None)
                else:
                    span_scope.__exit__(type(exc), exc, exc.__traceback__)
            finally:
                span_closed = True
            raise
        finally:
            for task in forwarder_tasks:
                task.cancel()
            await asyncio.gather(*forwarder_tasks, return_exceptions=True)
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
        content_str += content_to_safe_text(event.content)
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

    def _build_runnable_config(
        self,
        context_id: str,
        user_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
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
        if metadata is not None:
            configurable["metadata"] = metadata

        config: dict[str, Any] = {"configurable": configurable}
        if self.telemetry.enabled:
            # Use a fresh callback per turn: it owns a run_id -> open span map
            # while LangChain reports model starts/ends asynchronously.
            callback_attributes = {
                "agent.name": self.agent_name,
                "agent.runtime": "langgraph_chat",
                "session.id": context_id,
            }
            if task_id is not None:
                callback_attributes["task.id"] = task_id
            if user_id is not None:
                callback_attributes["user.id"] = user_id
            config["callbacks"] = [
                AutomaLLMCallbackHandler(
                    self.telemetry,
                    base_attributes=callback_attributes,
                )
            ]
            config["metadata"] = callback_attributes
        return config

    def _build_invoke_turn_result(
        self,
        response: Any,
        turn_inputs: TurnInputs,
    ) -> TurnResult:
        """Normalize a LangGraph invoke response into the hook result contract."""
        content = self._extract_response_content(response)
        assistant_text, artifact_text = self._split_artifact_content(content)
        return TurnResult(
            mode="invoke",
            content=assistant_text,
            artifact_content=artifact_text,
            raw_response=response,
            degraded=turn_inputs.degraded,
            missing_providers=turn_inputs.missing_providers,
        )

    def _extract_response_content(self, response: Any) -> str:
        """Best-effort extraction of assistant text from common invoke responses."""
        if isinstance(response, dict):
            messages = response.get("messages")
            if isinstance(messages, list) and messages:
                # LangGraph state usually carries the full message list; the
                # last message is the final assistant-visible response.
                return self._message_content_to_text(messages[-1])
            for key in ("content", "output", "response"):
                if key in response:
                    return self._message_content_to_text(response[key])
        return self._message_content_to_text(response)

    @staticmethod
    def _response_messages(response: Any) -> list[BaseMessage]:
        """Normalize common LangGraph response shapes into message objects."""
        if isinstance(response, BaseMessage):
            return [response]
        if isinstance(response, dict):
            messages = response.get("messages")
            if isinstance(messages, list):
                return [item for item in messages if isinstance(item, BaseMessage)]
        result = getattr(response, "result", None)
        if isinstance(result, list):
            return [item for item in result if isinstance(item, BaseMessage)]
        return []

    @classmethod
    def _model_usage_attributes(
        cls,
        messages: list[BaseMessage],
        *,
        session_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Extract token and model metadata from final LangChain messages."""
        totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        model = None
        provider = None
        response_model = None
        finish_reason = None

        for message in messages:
            usage = getattr(message, "usage_metadata", None) or {}
            metadata = getattr(message, "response_metadata", None) or {}
            model = model or metadata.get("model") or metadata.get("model_name")
            response_model = response_model or metadata.get("model_name")
            provider = provider or metadata.get("model_provider")
            finish_reason = (
                finish_reason
                or metadata.get("finish_reason")
                or metadata.get("stop_reason")
            )
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            total_tokens = int(
                usage.get("total_tokens") or input_tokens + output_tokens
            )
            totals["input_tokens"] += input_tokens
            totals["output_tokens"] += output_tokens
            totals["total_tokens"] += total_tokens

        attributes: dict[str, Any] = cls._event_identity_attributes(
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
        )
        has_model_usage_data = False
        if model is not None:
            attributes["model.name"] = model
            has_model_usage_data = True
        if response_model is not None:
            attributes["model.response_name"] = response_model
            has_model_usage_data = True
        if provider is not None:
            attributes["model.provider"] = provider
            has_model_usage_data = True
        if finish_reason is not None:
            attributes["model.finish_reason"] = finish_reason
            has_model_usage_data = True
        if totals["total_tokens"]:
            attributes["model.usage.input_tokens"] = totals["input_tokens"]
            attributes["model.usage.output_tokens"] = totals["output_tokens"]
            attributes["model.usage.total_tokens"] = totals["total_tokens"]
            has_model_usage_data = True

        return attributes if has_model_usage_data else None

    def _emit_model_usage_telemetry(
        self,
        messages: list[BaseMessage],
        *,
        session_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        attributes = self._model_usage_attributes(
            messages,
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
        )
        if attributes:
            self.telemetry.event("model.usage", attributes=attributes)

    @staticmethod
    def _message_content_to_text(value: Any) -> str:
        """Convert LangChain/OpenAI-style message content into plain text."""
        content = getattr(value, "content", value)
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text is not None:
                        parts.append(str(text))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(content)

    @staticmethod
    def _attachment_telemetry_attributes(
        attachments: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Return attachment metadata for telemetry without payload data."""
        normalized = [
            attachment
            for attachment in attachments or []
            if isinstance(attachment, Mapping)
        ]
        return {
            "message.attachments_count": len(normalized),
            "message.attachment_types": [
                str(attachment.get("mime_type") or "unknown")
                for attachment in normalized
            ],
        }

    @staticmethod
    def _split_artifact_content(content: str) -> tuple[str, str]:
        """Split assistant-visible text from artifact marker content."""
        if not content:
            return "", ""
        accumulator = AIMessageAccumulator()
        # Reuse the streaming parser so invoke and stream expose artifact text
        # with the same marker semantics.
        accumulator.add_chunk(AIMessageChunk(content=content))
        return (
            accumulator.get_assistant_text() or "",
            accumulator.get_artifact_text() or "",
        )

    async def _emit_final_output(
        self,
        output_queue: asyncio.Queue,
        message_accumulator: AIMessageAccumulator,
        session_id: str,
        task_id: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        degraded: bool = False,
        missing_providers: list[str] | None = None,
        stream_result: asyncio.Future[TurnResult] | None = None,
    ) -> None:
        """Emit the final stream item and publish the compact hook result."""
        missing_providers = missing_providers or []
        final_text = message_accumulator.get_assistant_text() or ""
        artifact_text = message_accumulator.get_artifact_text() or ""
        ai_message = message_accumulator.finalize()
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
        self._emit_model_usage_telemetry(
            [ai_message],
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
        )

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
                    output = {
                        "response_type": "data",
                        "is_task_complete": True,
                        "require_user_input": False,
                        "content": parsed,
                        "additional_artifacts": additional_artifacts,
                    }
                    if stream_result is not None and not stream_result.done():
                        stream_result.set_result(
                            TurnResult(
                                mode="stream",
                                content=final_text,
                                artifact_content=artifact_text,
                                final_output=output,
                                degraded=degraded,
                                missing_providers=missing_providers,
                            )
                        )
                    await output_queue.put(output)
                    return
            except Exception:
                # Intentionally pass.
                pass

        output = {
            "response_type": "text",
            "is_task_complete": True,
            "require_user_input": False,
            "content": final_text,
        }
        if stream_result is not None and not stream_result.done():
            stream_result.set_result(
                TurnResult(
                    mode="stream",
                    content=final_text,
                    artifact_content=artifact_text,
                    final_output=output,
                    degraded=degraded,
                    missing_providers=missing_providers,
                )
            )
        await output_queue.put(output)
