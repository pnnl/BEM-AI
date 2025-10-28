import logging
from typing import Dict

from a2a.types import AgentCard
from google.adk.models.lite_llm import LiteLlm
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.adk_agent import GenericADKAgent
from automa_ai.agents.react_langgraph_agent import GenericLangGraphReactAgent
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.common.utils import map_mcp_config_to_server_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def resolve_chat_model(backend: GenericLLM, model_name: str, base_url: str | None = None, api_key: str | None = None):

    if backend == GenericLLM.OLLAMA:
        return ChatOllama(model=model_name, base_url=base_url, temperature=0)
    elif backend == GenericLLM.OPENAI:
    # Need support for API key
        return ChatOpenAI(model=model_name, base_url=base_url, api_key=api_key)
    elif backend == GenericLLM.CLAUDE:
        assert api_key, "You must provide an API key to access Anthropic Claude model"
        return ChatAnthropic(model_name=model_name, base_url=base_url, api_key=api_key, timeout=None, stop=["}"])
    elif backend == GenericLLM.LITELLAMA:
        return LiteLlm(model=model_name)
    else:
        raise ValueError(f"Unsupported model backend: {backend}")


class AgentFactory:
    def __init__(
        self,
        card: AgentCard,
        instructions: str,
        model_name: str,
        agent_type: GenericAgentType,
        chat_model: GenericLLM,
        response_format: type[BaseModel] | None = None,
        mcp_configs: Dict[str, MCPServerConfig] | None = None,
        model_base_url: str | None = None,
        api_key: str | None = None,
    ):
        self.card = card
        self.instructions = instructions
        self.model_name = model_name
        self.agent_type = agent_type
        self.chat_model = chat_model
        self.response_format = response_format
        self.mcp_configs = mcp_configs
        self.model_base_url = model_base_url
        self.api_key = api_key

    def __call__(self) -> BaseAgent:
        chat_model = resolve_chat_model(self.chat_model, self.model_name, self.model_base_url, self.api_key)

        mcp_servers = None
        logger.info(f"Checking MCP servers to the agent: {self.card.name}...")
        if self.mcp_configs:
            mcp_servers = {
                server_name: map_mcp_config_to_server_config(config)
                for server_name, config in self.mcp_configs.items()
            }
        logger.info(f"Successful log the MCP servers for agent: {self.card.name}...")

        if self.agent_type == GenericAgentType.ADK:
            return GenericADKAgent(
                agent_name=self.card.name,
                description=self.card.description,
                instructions=self.instructions,
                chat_model=chat_model,
                mcp_servers=mcp_servers
            )

        elif self.agent_type == GenericAgentType.LANGGRAPH:
            return GenericLangGraphReactAgent(
                agent_name=self.card.name,
                description=self.card.description,
                instructions=self.instructions,
                response_format=self.response_format,
                chat_model=chat_model,
                mcp_servers=mcp_servers
            )

        raise ValueError(f"Unknown agent type: {self.agent_type}")
