from enum import Enum


class GenericAgentType(Enum):
    ADK = "adk"
    LANGGRAPH = "langgraph"


class GenericLLM(Enum):
    OPENAI = "openai"
    OLLAMA = "ollama"
    CLAUDE = "claude"
    LITELLAMA = "litellm"
