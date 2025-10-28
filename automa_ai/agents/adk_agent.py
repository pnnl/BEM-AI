import json
import logging
import re
from typing import Dict, AsyncIterable, Any

from google.adk import Agent
from google.adk.models import BaseLlm
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import SseServerParams
from google.genai import types as genai_types

from automa_ai.common.agent_runner import AgentRunner
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.types import ServerConfig

logging.basicConfig(
    filename="adk_agent.log",
    filemode="w",  # Overwrite each run
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


class GenericADKAgent(BaseAgent):
    """Generic implementation of Google ADK Agent"""

    def __init__(
        self,
        agent_name: str,
        description: str,
        instructions: str,
        chat_model: BaseLlm,
        mcp_servers: Dict[str, ServerConfig] | None = None,
    ):
        # Remove all empty strings - ADK agent name do not allow for empty spaces.
        agent_name = agent_name.replace(" ", "")
        super().__init__(
            agent_name=agent_name,
            description=description,
            content_types=["text", "text/plain"],
        )
        logger.info(f"Init {self.agent_name}")

        self.instructions = instructions
        self.agent = None
        assert (
            mcp_servers and len(mcp_servers) == 1
        ) or mcp_servers is None, (
            "Generic ADK agent only support connecting to one MCP server"
        )
        self.mcp_servers = mcp_servers
        self.chat_model = chat_model

    async def init_agent(self):
        logger.info(f"Initializing {self.agent_name} metadata")
        tools = []
        # Extract the key-value pair
        if self.mcp_servers:
            mcp_server, config = next(iter(self.mcp_servers.items()))
            logger.info(f"MCP server: {mcp_server} url={config.url}")

            # Load agent cards and tools
            tools = await MCPToolset(
                connection_params=SseServerParams(url=f"{config.url}/sse")
            ).get_tools()

            for tool in tools:
                logger.info(f"Loaded tools {tool.name}")

        generate_content_config = genai_types.GenerateContentConfig(temperature=0.0)
        self.agent = Agent(
            name=self.agent_name,
            instruction=self.instructions,
            model=self.chat_model,
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
            generate_content_config=generate_content_config,
            tools=tools,
        )
        self.runner = AgentRunner()

    async def invoke(self, query, session_id) -> dict:
        logger.info(f"Running {self.agent_name} for session {session_id}")
        raise NotImplementedError("Please use the streaming function.")

    async def stream(self, query, context_id, task_id) -> AsyncIterable[dict[str, Any]]:
        logger.info(
            f"Running {self.agent_name} stream for session {context_id} {task_id} - {query}"
        )
        if not query:
            raise ValueError("Query cannot be empty")
        if not self.agent:
            await self.init_agent()

        async for chunk in self.runner.run_stream(self.agent, query, context_id):
            if isinstance(chunk, dict) and chunk.get("type") == "final_result":
                response = chunk["response"]
                yield self.get_agent_response(response)
            else:
                yield {
                    "is_task_complete": False,
                    "require_user_input": False,
                    "content": f"{self.agent_name}: Processing Request...",
                }

    def format_response(self, chunk):
        patterns = [
            r"```\n(.*?)\n```",
            r"```json\s*(.*?)\s*```",
            r"```tool_outputs\s*(.*?)\s*```",
        ]

        for pattern in patterns:
            match = re.search(pattern, chunk, re.DOTALL)
            if match:
                content = match.group(1)
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return content
        return chunk

    def get_agent_response(self, chunk):
        logger.info(f"Response Type {type(chunk)}")
        data = self.format_response(chunk)
        logger.info(f"Formatted Response {data}")

        try:
            if isinstance(data, dict):
                if "status" in data and data["status"] == "input_required":
                    return {
                        "response_type": "text",
                        "is_task_complete": False,
                        "require_user_input": True,
                        "content": data["question"],
                    }
                return {
                    "response_type": "data",
                    "is_task_complete": True,
                    "require_user_input": False,
                    "content": data,
                }
            return_type = "data"
            try:
                data = json.loads(data)
                return_type = "data"
                if "status" in data and data["status"] == "input_required":
                    return {
                        "response_type": "text",
                        "is_task_complete": False,
                        "require_user_input": True,
                        "content": data["question"],
                    }
            except Exception as json_e:
                logger.error(f"Json conversion error {json_e}")
                return_type = "text"
            return {
                "response_type": return_type,
                "is_task_complete": True,
                "require_user_input": False,
                "content": data,
            }
        except Exception as e:
            logger.error(f"Error in get_agent_response: {e}")
            return {
                "response_type": "text",
                "is_task_complete": True,
                "require_user_input": False,
                "content": "Could not complete task. Please try again.",
            }
