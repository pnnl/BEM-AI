import asyncio
import os
from pathlib import Path

from a2a.types import AgentCard, AgentSkill, AgentCapabilities
from dotenv import load_dotenv

from automa_ai.agents import GenericAgentType, GenericLLM
from automa_ai.agents.agent_factory import AgentFactory
from automa_ai.common.agent_registry import A2AServerManager, A2AAgentServer
from automa_ai.retrieval import EmbeddingConfig, RetrieverProviderSpec
from automa_ai.retrieval.registry import register_retriever_provider
from examples.ruleset_checking.ruleset_retriever import RulesetRetrieverProvider

base_dir = Path(__file__).resolve().parent
env_path = base_dir / '.env'
load_dotenv(dotenv_path=env_path)

RCT_CHAT_BOT = """
You are an **Ruleset Checking Tool Assistant**. Your role is to assist users by providing guidance.
Keep your answer concise and always use chain-of-thought to address user's question.

# CHAIN OF THOUGHT PROCESS
## STEP 1:
- List all retrieved rules in **RULE DISPLAY FORMAT**
- If the List of retrieved rules has MORE than 3 rules:
    - Ask the user whether they would like to narrow down the number of rules by going through the **RULE FILTERING REASONING STEPS**.
- else
    - Ask the user to choose one rule to further investigate. MOVE TO STEP 2

## STEP 2:
- You need to follow the format below to analyze a rule:

```markdown
### Rule description: <rule_description>
## Rule Section: <Appendix_G_section>
## Rule evaluation: <Analyze the pseudo code in the rule_logic and provide a concise description of the rule evaluation>
```

### RULE DISPLAY FORMAT
```markdown
---
### Rule Section: 
<Appendix_G_section>
### Rule description: 
<rule_description>
---
### Rule Section: 
<Appendix_G_section>
### Rule description: 
<rule_description>
---
...
```

### RULE FILTERING REASONING STEPS
1. Review the relevant_context for each retrieved rule.
2. Identify what factor can help reduce the list of rules.
3. Ask user to provide additional information about this factor.
"""

CHATBOT_SERVER_URL = os.environ.get("CHATBOT_SERVER_URL")

# Define the primary skill
skill = AgentSkill(
    id="ruleset_analysis",
    name="Ruleset Assistant",
    description=(
        "Assistant to analysis rules"
    ),
    tags=["assistant", "energy code", "compliance", "helpdesk"],
    examples=[
        "I have a heat rejection device, what rules are applicable to my design",
    ],
)

# --8<-- [start:AgentCard]
# Public-facing agent card
public_agent_card = AgentCard(
    name="Ruleset Assistant Agent",
    description=(
        "Assistant to analysis rules"
    ),
    url=CHATBOT_SERVER_URL,
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill],  # Only the primary skill for the public card
    supports_authenticated_extended_card=False,
)

# chat_bot_model_name = os.environ.get("CHAT_BOT_MODEL_NAME")
chat_bot_model_name = os.environ.get("CLAUDE_MODEL_NAME")
chat_bot_base_url = os.environ.get("CHAT_BOT_MODEL_BASE_URL") or None

register_retriever_provider("rct_rules", RulesetRetrieverProvider)

retriever_spec = RetrieverProviderSpec(
    provider="rct_rules",
    top_k=10,
    embedding=EmbeddingConfig(
        provider="ollama",
        model="mxbai-embed-large",
        base_url=None,
    ),
    retrieval_provider_config={
        "db_path": str(Path(__file__).parent / "pipeline/chroma_persist"),
        "collection_name": "rct_rules",
    },
)

# Initialize chatbot agent
chatbot = AgentFactory(
    card=public_agent_card,
    instructions=RCT_CHAT_BOT,
    model_name=chat_bot_model_name,
    agent_type=GenericAgentType.LANGGRAPHCHAT,
    chat_model=GenericLLM.BEDROCK,
    # model_base_url=chat_bot_base_url,
    # mcp_configs={"retriever":retriever_mcp_config},
    retriever_spec=retriever_spec,
    enable_metrics=True,
    debug=True
)

# mcp_manager = MCPServerManager()
# mcp_manager.add_server(retriever_mcp_config)

# Wrap chatbot agent in A2A agent server
chatbot_a2a = A2AAgentServer(chatbot, public_agent_card, base_url_path="/permit")

# Initialize A2A server manager
server_manager = A2AServerManager()
# Add server
server_manager.add_server(chatbot_a2a)
# Start network


async def main():
    # await mcp_manager.start_all()
    # print("✅ MCP Server started at http://localhost:10000/")
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
    # await mcp_manager.stop_all()
    print("🧹 Server stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
