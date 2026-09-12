from enum import Enum

class GenericEmbedModel(Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"

class GenericAgentType(Enum):
    LANGGRAPH = "langgraph-task"
    LANGGRAPHCHAT = "langgraph-chat"
    ORCHESTRATOR = "orchestrator"

class GenericLLM(Enum):
    OPENAI = "openai"
    OLLAMA = "ollama"
    CLAUDE = "claude"
    GEMINI = "gemini"
    HUGGINGFACE = "huggingface"
    BEDROCK = "bedrock"
