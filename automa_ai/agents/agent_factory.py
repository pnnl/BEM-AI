import logging
import os
from typing import Dict, List

from a2a.types import AgentCard
from google.adk.models.lite_llm import LiteLlm
from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from pydantic import BaseModel, SecretStr

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.adk_agent import GenericADKAgent
from automa_ai.agents.langgraph_chatagent import GenericLangGraphChatAgent
from automa_ai.agents.orchestrator_network_agent import OrchestratorNetworkAgent
from automa_ai.agents.react_langgraph_agent import GenericLangGraphReactAgent
from automa_ai.agents.remote_agent import SubAgentSpec
from automa_ai.common.base_agent import BaseAgent
from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.retrieval import RetrieverProviderSpec, resolve_retriever
from automa_ai.common.utils import map_mcp_config_to_server_config, load_tool_plugins
from automa_ai.memory.manager import DefaultMemoryManager
from automa_ai.skills import SkillManager, SkillsConfig
from automa_ai.config.tools import ToolsConfig, ToolSpec
from automa_ai.config.blackboard import BlackboardConfig
from automa_ai.blackboard.backends.local_json import LocalJSONBlackboardStore
from automa_ai.blackboard.backends.s3_json import S3JSONBlackboardStore
from automa_ai.blackboard.backends.dynamodb_json import DynamoDBJSONBlackboardStore
from automa_ai.blackboard.instructions import build_blackboard_contract
from automa_ai.blackboard.schema import BlackboardSchemaRegistry, BlackboardSchemaValidator
from automa_ai.blackboard.errors import BackendNotConfiguredError

logger = logging.getLogger(__name__)


def resolve_chat_model(
    backend: GenericLLM,
    model_name: str,
    agent_type: GenericAgentType,
    base_url: str | None = None,
    api_key: str | None = None,
    api_version: str | None = None,
):
    if backend == GenericLLM.OLLAMA:
        return ChatOllama(model=model_name, base_url=base_url, temperature=0)
    elif backend == GenericLLM.BEDROCK:
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_region = os.getenv("AWS_REGION")
        if aws_access_key_id is None or aws_secret_access_key is None:
            logger.warning(
                "AWS_ACCESS_KEY_ID, AWS_REGION, AWS_SECRET_ACCESS_KEY are not set"
            )
            return ChatBedrockConverse(
                model=model_name, region_name=aws_region, temperature=0
            )
        return ChatBedrockConverse(
            model=model_name,
            region_name=aws_region,
            aws_access_key_id=SecretStr(aws_access_key_id),
            aws_secret_access_key=SecretStr(aws_secret_access_key),
        )
    elif backend == GenericLLM.OPENAI:
        assert api_key, "You must provide an API key to access OpenAI GPT models"
        # Need support for API key
        # Detect Azure automatically
        if base_url and "azure.com" in base_url.lower():
            # Azure OpenAI
            if not api_version:
                raise ValueError(
                    "AzureChatOpenAI requires azure_api_version and azure_deployment"
                )
            streaming = True if agent_type is GenericAgentType.LANGGRAPHCHAT else False
            return AzureChatOpenAI(
                azure_endpoint=base_url,
                api_key=SecretStr(api_key),
                api_version=api_version,
                azure_deployment=model_name,
                streaming=streaming,
            )
        return ChatOpenAI(
            model=model_name,
            base_url=base_url,
            api_key=SecretStr(api_key),
            temperature=0,
            streaming=True,
        )
    elif backend == GenericLLM.CLAUDE:
        assert api_key, "You must provide an API key to access Anthropic Claude model"
        key = SecretStr(api_key)
        return ChatAnthropic(
            model_name=model_name,
            base_url=base_url,
            temperature=0,
            api_key=key,
            timeout=None,
            stop=["}"],
        )
    elif backend == GenericLLM.GEMINI:
        assert os.getenv(
            "GOOGLE_API_KEY"
        ), "You must add GOOGLE_API_KEY in the system environment."
        streaming = True if agent_type is GenericAgentType.LANGGRAPHCHAT else False
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            timeout=None,
            max_retries=2,
            max_tokens=None,
            streaming=streaming,
        )
    elif backend == GenericLLM.LITELLAMA:
        return LiteLlm(model=model_name)
    else:
        raise ValueError(f"Unsupported model backend: {backend}")


class AgentFactory:
    """
    Default Agent Factory to create a callable agent
    Param:
        card: AgentCard Agent card stored in AgentCard object
        instruction: str system prompt - system prompt does not accept the prompt template. It is simply an instruction for the agent
        model_name: str the name of the language model
        agent_type: GenericAgentType specify the agent type, currently available includes langgraph task and langgraph chat, orchestrator, (google ADK is not tested)
        chat_model: GenericLLM specify the language model framework, currently supports openai, ollama and claude
        response_format: BaseModel Response format
        mcp_configs: Dict[str, MCPServerConfig] | None Default None, mcp servers the agent connect to.
                Examples: {
                            "sample_mcp_1": MCPServerConfig(name="sample_mcp", host="localhost", port=10000, transport="sse"),
                            }
        retriever: BaseRetriever | dict | None = None Default None, knowledge base retrieval function.
        enable_metrics: bool determine whether metrics tracking per task / query should be enabled or not.
        debug: bool determine whether debug mode should be enabled or not.
    """

    def __init__(
        self,
        card: AgentCard,
        instructions: str,
        model_name: str,
        agent_type: GenericAgentType,
        chat_model: GenericLLM,
        response_format: type[BaseModel] | None = None,
        mcp_configs: Dict[str, MCPServerConfig] | None = None,
        retriever_spec: RetrieverProviderSpec | dict | None = None,
        subagent_config: List[SubAgentSpec] | None = None,
        memory_config: Dict | None = None,
        skills_config: SkillsConfig | Dict | None = None,
        tools_config: ToolsConfig | Dict | List[Dict] | None = None,
        blackboard_config: BlackboardConfig | Dict | None = None,
        model_base_url: str | None = None,
        api_key: str | None = None,
        api_version: str | None = None,
        enable_metrics: bool = False,
        debug: bool = False,
    ):
        self.card = card
        self.instructions = instructions
        self.model_name = model_name
        self.agent_type = agent_type
        self.chat_model = chat_model
        self.response_format = response_format
        self.mcp_configs = mcp_configs
        self.retriever_spec = retriever_spec
        self.subagent_config = subagent_config
        self.memory_config = memory_config
        self.skills_config = skills_config
        self.tools_config = tools_config
        self.blackboard_config = blackboard_config
        self.model_base_url = model_base_url
        self.api_key = api_key
        self.api_version = api_version
        self.enable_metrics = enable_metrics
        self.debug = debug

    def get_agent(self):
        return self.__call__()

    def __call__(self) -> BaseAgent:
        load_tool_plugins()

        chat_model = resolve_chat_model(
            self.chat_model,
            self.model_name,
            self.agent_type,
            self.model_base_url,
            self.api_key,
            self.api_version,
        )

        mcp_servers = None
        logger.info(f"Checking MCP servers to the agent: {self.card.name}...")
        if self.mcp_configs:
            mcp_servers = {
                server_name: map_mcp_config_to_server_config(config)
                for server_name, config in self.mcp_configs.items()
            }
        logger.info(f"Successful log the MCP servers for agent: {self.card.name}...")
        logger.info(f"Initializing a {self.agent_type.value} agent")

        # Resolve memories
        memory_manager = None
        if self.memory_config:
            memory_manager = DefaultMemoryManager.from_config(self.memory_config)

        skill_manager = None
        if self.skills_config:
            config = self.skills_config
            if not isinstance(config, SkillsConfig):
                config = SkillsConfig.from_dict(config)
            if config.enabled:
                skill_manager = SkillManager(config)

        blackboard_store = None
        blackboard_contract = None
        blackboard_schema_name = None
        blackboard_schema_version = None
        blackboard_initial_data = None
        if self.blackboard_config:
            bb_cfg = self.blackboard_config
            if not isinstance(bb_cfg, BlackboardConfig):
                bb_cfg = BlackboardConfig.from_dict(bb_cfg)
            if bb_cfg.enabled:
                registry = BlackboardSchemaRegistry()
                registry.register(
                    name=bb_cfg.schema_name,
                    version=bb_cfg.schema_version,
                    json_schema=bb_cfg.schema,
                    description=bb_cfg.schema_description,
                )
                validator = BlackboardSchemaValidator(registry)
                if bb_cfg.backend == "local_json":
                    blackboard_store = LocalJSONBlackboardStore(base_dir=bb_cfg.base_dir or ".blackboard", validator=validator)
                elif bb_cfg.backend == "s3_json":
                    if not bb_cfg.s3_bucket:
                        raise BackendNotConfiguredError("s3_bucket is required for s3_json backend.")
                    blackboard_store = S3JSONBlackboardStore(
                        bucket=bb_cfg.s3_bucket,
                        prefix=bb_cfg.s3_prefix,
                        validator=validator,
                    )
                elif bb_cfg.backend == "dynamodb_json":
                    if not bb_cfg.dynamodb_table:
                        raise BackendNotConfiguredError("dynamodb_table is required for dynamodb_json backend.")
                    blackboard_store = DynamoDBJSONBlackboardStore(table_name=bb_cfg.dynamodb_table, validator=validator)
                else:
                    raise BackendNotConfiguredError(f"Unknown blackboard backend: {bb_cfg.backend}")

                blackboard_schema_name = bb_cfg.schema_name
                blackboard_schema_version = bb_cfg.schema_version
                blackboard_initial_data = bb_cfg.initial_data
                blackboard_contract = build_blackboard_contract(
                    registry.resolve(bb_cfg.schema_name, bb_cfg.schema_version)
                )

        built_tool_specs: list[ToolSpec] | None = None
        if self.tools_config:
            if isinstance(self.tools_config, ToolsConfig):
                built_tool_specs = self.tools_config.tools
            elif isinstance(self.tools_config, list):
                built_tool_specs = [
                    ToolSpec.model_validate(item) for item in self.tools_config
                ]
            else:
                built_tool_specs = ToolsConfig.from_dict(self.tools_config).tools

        if self.agent_type == GenericAgentType.ADK:
            return GenericADKAgent(
                agent_name=self.card.name,
                description=self.card.description,
                instructions=self.instructions,
                chat_model=chat_model,
                mcp_servers=mcp_servers,
            )
        elif self.agent_type == GenericAgentType.LANGGRAPHCHAT:
            return GenericLangGraphChatAgent(
                agent_name=self.card.name,
                description=self.card.description,
                instructions=self.instructions,
                response_format=self.response_format,
                chat_model=chat_model,
                mcp_servers=mcp_servers,
                retriever=(
                    resolve_retriever(self.retriever_spec)
                    if self.retriever_spec
                    else None
                ),
                subagents=self.subagent_config if self.subagent_config else None,
                skills_manager=skill_manager,
                default_tools=built_tool_specs,
                blackboard_store=blackboard_store,
                blackboard_schema_name=blackboard_schema_name,
                blackboard_schema_version=blackboard_schema_version,
                blackboard_initial_data=blackboard_initial_data,
                blackboard_contract=blackboard_contract,
                memory_manager=memory_manager,
                enable_metrics=self.enable_metrics,
                debug=self.debug,
            )

        elif self.agent_type == GenericAgentType.LANGGRAPH:
            return GenericLangGraphReactAgent(
                agent_name=self.card.name,
                description=self.card.description,
                instructions=self.instructions,
                response_format=self.response_format,
                chat_model=chat_model,
                mcp_servers=mcp_servers,
                enable_metrics=self.enable_metrics,
                debug=self.debug,
            )

        elif self.agent_type == GenericAgentType.ORCHESTRATOR:
            return OrchestratorNetworkAgent(
                agent_name=self.card.name,
                description=self.card.description,
                instructions=self.instructions,
                chat_model=chat_model,
            )

        raise ValueError(f"Unknown agent type: {self.agent_type}")
