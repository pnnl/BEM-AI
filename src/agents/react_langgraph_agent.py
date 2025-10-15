import json
import logging
import re
from json import JSONDecodeError
from typing import Dict, AsyncIterable, Any

from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_core.messages import AIMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from common.base_agent import BaseAgent
from common.response_parser import extract_and_parse_json
from common.types import ServerConfig

memory = MemorySaver()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GenericLangGraphReactAgent(BaseAgent):
    """A generic LangGraph react agent"""

    def __init__(
        self,
        agent_name: str,
        description: str,
        instructions: str,
        chat_model: LanguageModelLike,
        response_format: type[BaseModel] | None,
        mcp_servers: Dict[str, ServerConfig] | None = None,
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
                # print(self.agent_name, f"Loaded tools {tool.name}")
                logger.info(f"Loaded tools {tool.name}")

        self.graph = create_react_agent(
            self.model,
            checkpointer=memory,
            prompt=self.instructions,
            response_format=self.response_format,
            tools=tools,
        )

    async def invoke(self, query, sessionId):
        config = {"configurable": {"thread_id": sessionId}}
        await self.graph.ainvoke({"messages": [("user", query)]}, config)
        return self.get_agent_response(config)

    async def stream(self, query, sessionId, task_id) -> AsyncIterable[dict[str, Any]]:
        inputs = {"messages": [("user", query)]}
        config = {"configurable": {"thread_id": sessionId}}
        logger.info(
            f"Running planner agent stream for session {sessionId} {task_id} with input {query}"
        )
        if not self.graph:
            await self.init_graph()
        # seen_messages = set()
        # Collect all streaming messages first
        last_item = None
        async for item in self.graph.astream(inputs, config, stream_mode="values"):
            last_item = item
            print(self.agent_name, " message: ", item)
            if "messages" in item:
                # Take out the last AI Message
                message = item["messages"][-1]
                logger.info(f"Streaming message: {message}")
                # print(
                #    f"Message type is: {type(message)}, and message is: {isinstance(message, AIMessage)} item type is: {type(item)}"
                #)
                logger.info(
                    f"Message type is: {type(message)}, and message is: {isinstance(message, AIMessage)} item type is: {type(item)}"
                )
                if isinstance(message, AIMessage) and message.tool_calls:
                    # this is a tool call AI Message, do not yield
                    continue
                if isinstance(message, AIMessage) and message.content:
                    content = message.content.strip()
                    # print(f"Streaming content: {content}")
                    if content.startswith("<think>") or content.endswith("</think>"):
                        # Remove <think>...</think> (including newlines and spaces around it)
                        content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)
                    # Skip ToolMessage and HumanMessage and make sure there is content in the AI message (not a tool calling AI message, which typically has no content.)
                    try:
                        _, parsed = extract_and_parse_json(content)
                        # This only works with the llama3.1:8b when it explicitly gives CHAIN OF THOUGHT PROCESS in the output
                        # despite the prompts ask only JSON
                        # print(self.agent_name, ": ", content)
                        # print("parsed: ", parsed)
                        logger.info(
                            f"Loading the message json: {parsed}, status: {parsed.get('status')}"
                        )
                        # print(
                        #    f"Loading the message json: {parsed}, status: {parsed.get('status')}"
                        #)
                        if isinstance(parsed, dict):
                            if parsed.get("type") == "function":
                                # I dont know why but I am keep getting this from AI messages.
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
                                logger.info(f"completed task: {parsed}")
                                yield {
                                    "response_type": "data",
                                    "is_task_complete": True,
                                    "require_user_input": False,
                                    "content": parsed,
                                }
                            elif parsed.get("status") == "input_required":
                                logger.info(f"input required task: {parsed}")
                                yield {
                                    "response_type": "text",
                                    "is_task_complete": False,
                                    "require_user_input": True,
                                    "content": parsed["question"],
                                }
                            else:
                                # we dont know what is the status, it could be just thinking or asking user to clarify
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
                        logger.info(f"Failed parsing JSON data, error message: {jde}")
                        print(f"Failed parsing JSON data, error message: {jde}")
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
                    except Exception as e:
                        logger.info(f"Failed matching the ai message, error message: {e}")
                        # print(f"Failed matching the ai message, error message: {e}")
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
                        "content": f"Unable to determine next steps. Please try again. item {last_item}",
                    }

