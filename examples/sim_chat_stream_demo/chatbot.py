import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.agent_registry import A2AServerManager, A2AAgentServer
from automa_ai.common.mcp_registry import MCPServerConfig, MCPServerManager
from automa_ai.memory.memory_types import MemoryType
from examples.sim_chat_stream_demo.mcp_server.mcp_server import serve

base_dir = Path(__file__).resolve().parent
env_path = base_dir / '.env'
load_dotenv(dotenv_path=env_path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

## Register memory plugin
from automa_ai.memory.manager import MemoryStoreRegistry
from automa_ai.memory.sqlite_memory_store import SQLiteMemoryStore
from automa_ai.memory.chroma_memory_store import ChromaVectorMemoryStore

MemoryStoreRegistry.register("default_sqlite", SQLiteMemoryStore)
MemoryStoreRegistry.register("default_chroma", ChromaVectorMemoryStore)

# MCP server
weather_mcp_config = MCPServerConfig(
    name="weather_mcp",
    host="localhost",
    port=10000,
    serve=serve,
    transport="streamable-http"
)

# skill configuration
skill_config = {
    "enabled": True,
    "allowed_roots": [f"{base_dir}/skills"],
    "registry": {
        "predict_weather": {
            "path": f"{base_dir}/skills/predict_weather.md",
            "format": "markdown",
        },
    },
}

tools_config = {
    "tools": [
        {
            "type": "web_search",
            "config": {
                "provider": "opensource",
            },
        }
    ]
}


CHAT_COT = """
You are AUTOMA-AI, a dynamic multi-agent network system built on Google's A2A and Anthropic's MCP protocols, combining the power of LangChain, Google GenAI, and modern agent orchestration for engineering task orchestration.
Your task is to provide helpful information for users to use AUTOMA-AI.

If asked about weather, you should load the predict_weather skill and follow the instruction to respond user query.
If the answer is not in the sample code or depends on current external information, use the web_search tool before answering.

Always use the CHAIN-OF-THOUGHT PROCESS before answering user questions.

CHAIN-OF-THOUGHT PROCESS:
Before each response, reason through:
1. What information does the user want to know? [Understand user question]
2. What information do I already have to answer user's question? [List all known information]
3. What is the next unknown information? [Identify gap]
4. If I dont have the information, can I find them in the SAMPLE CODE? [Try to search for information]
4. If I cannot find the unknown information, how should i naturally ask for this information? [Formulate question]
5. If I have all the information, I should then provide the final answer to the user.

SAMPLE CODE:
## Sample 1. Create an Agent:
There are three steps to create an agent:
Step 1: Define agent skills and agent card
```python
skill = AgentSkill(
    id="eplus_assis",
    name="EnergyPlus Assistant",
    description="Provide explanation to EnergyPlus questions",
    tags=["assistant"],
    examples=["What does EnergyPlus do", "Where can we download EnergyPlus"],
)

# --8<-- [start:AgentCard]
# This will be the public-facing agent card
public_agent_card = AgentCard(
    name="Chat Bot Agent",
    description="An expert in building energy modeling and happy to have a chat with peers.",
    url="http://localhost:20000",
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill],  # Only the basic skill for the public card
    supports_authenticated_extended_card=False,
)
```
Step 2: Create an Agent using AgentFactory - remember to provide a chat prompt
```python
chat_agent = AgentFactory(
    card=public_agent_card,
    instructions=chat_prompt,
    model_name="llama3.1:8b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
)
```
Step 3: Invoke chat:
```python
responses = await chat_agent.get_agent().invoke("What is the latest version of EnergyPlus?", "test_session_2")
for message in responses["messages"]:
    if isinstance(message, HumanMessage):
        print(f"User: {message.content} \n\n")
    elif isinstance(message, AIMessage):
        print(f"Assistant: {message.content} \n\n")
```
## Sample 2. Start an A2A agent server:
After created an agent, you can wrap the agent with A2AServer
```python
# Wrap chatbot agent in A2A agent server
chatbot_a2a = A2AAgentServer(chatbot, public_agent_card)
```

## Sample 3. Use the A2A agent server manager
You can create multiple A2A agent servers using A2A agent server manager to start the server
```python
# Initialize A2A server manager
server_manager = A2AServerManager()
# Add server
server_manager.add_server(chatbot_a2a)
server_manager.add_server(evaluation_a2a)

```

## Sample 4. How to make an agent subscribe to an MCP server or multiple of them
You can subscribe an MCP server to an agent through MCP Configuration
```python
oss_schema_mcp_config = MCPServerConfig(
            name="oss_schema_mcp",
            host="localhost",
            port=10110,
            serve=os_mcp.serve,
            transport="sse"
    )

chat_agent = AgentFactory(
    card=public_agent_card,
    instructions=chat_prompt,
    model_name="llama3.1:8b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    mcp_configs={"oss_schema_mcp": oss_schema_mcp_config}
)
```

## Sample 5. 
You can also create an MCP server and start it with MCP server manager
```python
oss_schema_mcp_config = MCPServerConfig(
            name="oss_schema_mcp",
            host="localhost",
            port=10110,
            serve=os_mcp.serve,
            transport="sse"
    )
self.mcp_manager = MCPServerManager()
mcp_manager.add_server(oss_schema_mcp_config)
mcp_manager.start_all()
```
"""

CHATBOT_SERVER_URL = os.environ.get("CHATBOT_SERVER_URL")

skill = {
    "id": "automa_assistant",
    "name": "Automa AI Assistant",
    "description": "Assistant to explain what is automa and how to work with automa",
    "tags": ["assistant"],
    "examples": ["Tell me about yourself", "Can you tell me what you can do?"],
}

# --8<-- [start:AgentCard]
# This will be the public-facing agent card
public_agent_card = {
    "name": "Automa AI Assistant Agent",
    "description": "Assistant to provide support and help to users using automa_ai package.",
    "version": "1.0.0",
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "capabilities": {
        "streaming": True,
    },
    "supportedInterfaces": [
        {
            "url": CHATBOT_SERVER_URL,
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
    "skills": [skill],
}
chat_bot_model_name = os.environ.get("CHAT_BOT_MODEL_NAME")
chat_bot_base_url = os.environ.get("CHAT_BOT_MODEL_BASE_URL") or None

# Initialize chatbot agent
chatbot = AgentFactory(
    card=public_agent_card,
    instructions=CHAT_COT,
    model_name=chat_bot_model_name,
    agent_type=GenericAgentType.LANGGRAPHCHAT,
    chat_model=GenericLLM.OLLAMA,
    model_base_url=chat_bot_base_url,
    mcp_configs={"weather_mcp": weather_mcp_config},
    skills_config=skill_config,
    tools_config=tools_config,
    enable_metrics=True,
    debug=True
)

# Wrap chatbot agent in A2A agent server
chatbot_a2a = A2AAgentServer(chatbot, public_agent_card)

# Initialize MCP server manager
mcp_manager = MCPServerManager()
mcp_manager.add_server(weather_mcp_config)

# Initialize A2A server manager
server_manager = A2AServerManager()
# Add server
server_manager.add_server(chatbot_a2a)
# Start network


async def main():
    await mcp_manager.start_all()
    print("✅ MCP Server started at http://localhost:10000/")
    await server_manager.start_all()
    print("✅ A2A Server started at http://localhost:9999/")
    print("Type 'exit' or 'stop' to shut down.")

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    async def wait_for_input():
        while True:
            cmd = await loop.run_in_executor(None, input, "> ")
            if cmd.strip().lower() in {"exit", "stop", "quit"}:
                stop_event.set()
                break

    await wait_for_input()
    print("🛑 Stopping server...")
    await server_manager.stop_all()
    await mcp_manager.stop_all()
    print("🧹 Server stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
