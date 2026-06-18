from enum import Enum

class GenericEmbedModel(Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"

class GenericAgentType(Enum):
    ADK = "adk"
    LANGGRAPH = "langgraph-task"
    LANGGRAPHCHAT = "langgraph-chat"
    ORCHESTRATOR = "orchestrator"

class GenericLLM(Enum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai-compatible"
    OLLAMA = "ollama"
    CLAUDE = "claude"
    GEMINI = "gemini"
    LITELLAMA = "litellm"
    HUGGINGFACE = "huggingface"
    BEDROCK = "bedrock"
