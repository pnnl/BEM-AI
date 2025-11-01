import asyncio

from a2a.types import AgentCard, AgentSkill, AgentCapabilities

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.agent_registry import A2AServerManager, A2AAgentServer

SUMMARY_COT = """
Your job is to summarize a query from user.
Your summary shall follow the format below.

In each section, there is an instruction to follow when generating the summary.

### Task
{query}

### Building Energy Modeling Task
In this section, you need to analyze what task has been performed by reading the {results}

### Modeling Meta Data
In this section, provide a summary based on {blackboard}

### Summary
Based on the above information, summarize the work that has performed in this task.

"""
CHATBOT_SERVER_URL = "http://localhost:9999/"

skill = AgentSkill(
        id='automa_assistant',
        name='Automa AI Assistant',
        description='Assistant to explain what is automa and how to work with automa',
        tags=['assistant'],
        examples=['Tell me about yourself', 'Can you tell me what you can do?'],
)

# --8<-- [start:AgentCard]
# This will be the public-facing agent card
public_agent_card = AgentCard(
    name='Automa AI Assistant Agent',
    description='Assistant to provide support and help to users using automa_ai package.',
    url=CHATBOT_SERVER_URL,
    version='1.0.0',
    default_input_modes=['text'],
    default_output_modes=['text'],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill],  # Only the basic skill for the public card
    supports_authenticated_extended_card=False,
)

# Initialize chatbot agent
chatbot = AgentFactory(
    card=public_agent_card,
    instructions=SUMMARY_COT,
    model_name="llama3.3:70b",
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    model_base_url="http://rc-chat.pnl.gov:11434"
)

# Wrap chatbot agent in A2A agent server
chatbot_a2a = A2AAgentServer(chatbot, public_agent_card)

# Initialize A2A server manager
server_manager = A2AServerManager()
# Add server
server_manager.add_server(chatbot_a2a)
# Start network

async def main():
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
    print("🧹 Server stopped cleanly.")

if __name__ == "__main__":
    asyncio.run(main())
