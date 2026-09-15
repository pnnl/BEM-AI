from enum import Enum

class GenericEmbedModel(Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"

class GenericAgentType(Enum):
    LANGGRAPHCHAT = "langgraph-chat"

class GenericLLM(Enum):
    OPENAI = "openai"
    OLLAMA = "ollama"
    CLAUDE = "claude"
    GEMINI = "gemini"
    HUGGINGFACE = "huggingface"
    BEDROCK = "bedrock"
