# AUTOMA-AI - Autonomous Multi-Agent Network (Formerly BEM-AI)

AUTOMA-AI is an open-source framework for building production-ready AI agents powered by modern language models such as Gemini, ChatGPT, and Claude.

It provides a structured way to turn LLMs from simple chat interfaces into task-oriented agents that can plan, reason, and interact with external systems. Out of the box, AUTOMA-AI equips agents with capabilities such as:

- **Tool and API integration** (via MCP or AUTOMA-AI tool interface)
- **Retrieval pipelines** for grounding responses in data
- **Memory systems** for session and long-term context
- **Skills and workflows** for structured task execution
- **Multi-agent orchestration** for complex problem-solving

AUTOMA-AI is designed with real-world deployment in mind. It supports AWS-based architectures and integrates with major cloud services, enabling teams to move from prototype to production quickly.

Under the hood, the framework builds on emerging standards like **Google’s A2A (Agent-to-Agent)** and **Anthropic’s MCP (Model Context Protocol)**, and leverages ecosystems such as LangChain and modern orchestration patterns to coordinate agents in engineering workflows.

Ready to use automa-ai? do:

```bash
pip install automa-ai
```
Wanna start a AI development with automa-ai? Don't miss the [sim_chat_stream_demo](examples/sim_chat_stream_demo) example to help you bootstrap an AI chatbot.

NOTE:
**BEM-AI** has moved to an example folder: [bem-ai](examples/sim_bem_network)

## ⚠️ Project Status

This project is in its **early development phase** and is considered **highly unstable**. APIs, interfaces, and core functionality are subject to significant changes. Use for development and experimentation only.

## 🚀 Overview

AUTOMA-AI creates a distributed multi-agent system that enables intelligent agents to communicate, collaborate, and coordinate using industry-standard protocols. The system leverages:

- **Google A2A Protocol**: For agent-to-agent communication
- **Anthropic MCP Protocol**: For model context management
- **LangChain / LangGraph**: For LLM-based agent orchestration and workflow management
- **Google GenAI**: For AI model integration

## 🛠️ Technology Stack

### Core Dependencies
- **LangChain / LangGraph**: Agent framework and orchestration
- **Google GenAI**: AI model integration
- **Google A2A**: Agent-to-agent communication protocol
- **Anthropic MCP**: Model context protocol implementation

### Development Tools
- **uv**: Modern Python package management
- **Python 3.12**: Runtime environment

## 📁 Project Structure

```
BEM-AI/
├── examples/                           # Example engineering applications built with the foundational framework
├── automa_ai/
│   ├── agent_test/                     # Test implementations and examples
│   ├── agents/                         # Generic agent classes
│   │   ├── react_langgraph_agent.py    # langchain/langgraph based agent
│   │   ├── agent_factor.py             # Agent factory - recommend utility to initialize an agent
│   │   ├── orchestrator_agent.py       # An agent that orchestrates the task workflow
│   │   └── adk_agent.py                # Google ADK based agent
│   ├── client/                         # Under development
│   ├── mcp_servers/                    # MCP library
│   ├── network/                        # Network
│   ├── common/                         # Common utilities
│   └── prompts/                        # Shared prompt templates
├── pyproject.toml                      # Project configuration
├── uv.lock                             # Dependency lock file
└── README.md                           # This file
```

## 🔧 Installation
We recommend install AUTOMA-AI through PYPI:
```shell
pip install automa-ai
```
This will install all packages needed under automa_ai folder.


### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd bem-ai
   ```

2. **Install dependencies using uv**
   ```bash
   uv sync
   ```

3. **Activate the virtual environment**
   ```bash
   uv shell
   ```

## 🧪 Running Tests
TBD

## 🏗️ Architecture
<img src="sources/architecture.png" alt="System Architecture" width="600">

- **Orchestrator**: Assemble workflow, access agent card storage
- **Task Memory**: Task memory including shared blackboard and conversation history
- **Planner**: A planner agent
- **Summary**: A summary agent
- **Specialized agents**: Domain specific agents
- **Agent Card Service**: A RAG pipeline stores agent cards
- **Tool and Resources**: External tool and resource access through MCPs

## 📝 Configuration

Project configuration is managed through `pyproject.toml`. Key configuration areas include:

- **Dependencies**: Core and development packages
- **Build System**: uv-based build configuration
- **Project Metadata**: Version, description, and author information
- **Optional**: optional packages to use for UI integration and running examples.

### Default tools configuration

You can enable built-in tools directly from config using a `tools` list.

```yaml
tools:
  - type: web_search
    config:
      provider: auto
      serper:
        api_key: ${SERPER_API_KEY}
      firecrawl:
        api_key: ${FIRECRAWL_API_KEY}
      scrape:
        enabled: true
        max_pages: 5
      rerank:
        provider: opensource
        top_k: 5
  - type: run_python
    config:
      runner: local_subprocess
      timeout_s: 20
      workspace_root: .
      allow_network: false  # Import-policy toggle only; not runtime network isolation.
  - type: run_command
    config:
      profile: exploration
      timeout_s: 20
      workspace_root: .
```

Then pass this to `AgentFactory(..., tools_config=tools)` for `LANGGRAPHCHAT` agents.
See `docs/tools.md`, `examples/web_search_demo.py`, and `examples/run_python_demo.py` for runnable examples.

### Checkpointer configuration

`LANGGRAPHCHAT` agents can also be configured with an explicit checkpointer backend through `AgentFactory`.
The default backend is in-memory. Redis is opt-in and requires a connection URL.

There are two Redis backends:

- `redis_plain`: Uses only core Redis commands. Choose this for standard Redis-compatible deployments, including typical Amazon ElastiCache deployments that do not expose RediSearch and RedisJSON.
- `redis_stack`: Uses LangGraph's Redis saver and requires both RediSearch and RedisJSON support. Choose this only when your Redis deployment supports commands such as `FT._LIST` and `JSON.GET`.

Use `type: default` to force the in-memory saver explicitly.

#### `redis_plain`

```yaml
checkpointer:
  type: redis_plain
  redis_url: redis://localhost:6379
```

`redis_plain` is intended for deployments where you want Redis-backed checkpoint persistence without Redis module dependencies.
This is the safest choice for plain ElastiCache Redis/Valkey deployments.

#### `redis_stack`

```yaml
checkpointer:
  type: redis_stack
  redis_url: redis://localhost:6379
```

Then pass this to `AgentFactory(..., checkpointer_config=checkpointer)`.

At startup, AUTOMA-AI validates that the configured Redis server supports:

- `FT._LIST` for RediSearch
- `JSON.GET` for RedisJSON

If either command is unavailable, startup fails with a clear error and tells you to switch to `redis_plain`.

#### Choosing the backend

- Choose `redis_plain` when your deployment target is standard Redis or ElastiCache and you do not specifically need Redis Stack modules.
- Choose `redis_stack` only when the Redis service is known to support RediSearch and RedisJSON.
- Do not use the old ambiguous `redis` label. The backend must be selected explicitly.

### A2A Server Configuration

#### Base Path

You can mount an A2A agent server under a URL prefix by passing `base_url_path` to
`A2AAgentServer`. This is useful when serving behind a reverse proxy or when you
want a dedicated path segment for the agent.

```python
from automa_ai.common.agent_registry import A2AAgentServer

chatbot_a2a = A2AAgentServer(chatbot, public_agent_card, base_url_path="/permit")
```

Notes:
- Include a trailing slash in client URLs to avoid 307 redirects (SSE does not
  follow redirects): e.g., 

```python 
SimpleClient(agent_url=f"{A2A_SERVER_URL}/permit/")
```

#### Health Check Endpoint

Every A2A server automatically includes a health check endpoint that returns the agent's status. By default, it's available at `/health`, but you can customize the path:

```python
chatbot_a2a = A2AAgentServer(
    chatbot, 
    public_agent_card, 
    health_check_path="/status"
)
```

The health check returns a JSON response:
```json
{
  "status": "healthy",
  "agent": "Your Agent Name"
}
```

The status is `"healthy"` when the agent is initialized and ready, or `"unhealthy"` during startup.

### Retriever configuration

Automa-AI retrieval uses a provider-based spec (by name or dotted import path). Registry names must
be registered with `register_retriever_provider(...)`, and only the embedding section is standardized;
`retrieval_provider_config` is passed through to the selected provider.

**Registered provider (registry name)**
```yaml
retriever:
  enabled: true
  provider: "helpdesk_chroma"
  top_k: 6
  embedding:
    provider: "ollama"
    model: "nomic-embed-text"
    api_key: null
    base_url: "http://localhost:11434"
    extra: {}
  retrieval_provider_config:
    db_path: "/data/chroma"
    collection_name: "my_collection"
```

**Custom provider (dotted import path)**
```yaml
retriever:
  enabled: true
  impl: "my_project.retrieval:MyRetrieverProvider"
  top_k: 10
  embedding:
    provider: "openai"
    model: "text-embedding-3-large"
    api_key: "${OPENAI_API_KEY}"
    base_url: null
    extra:
      dimensions: 3072
  retrieval_provider_config:
    index_name: "prod-index"
    namespace: "tenant-a"
    pinecone_api_key: "${PINECONE_API_KEY}"
    pinecone_env: "us-west-2"
```

## Examples
#### Single Agent Chatbot with Streamlit UI interface
This example demonstrates the use of automa-ai for creating a live-streaming chatbot.
The example uses QWEN3:4B as the language model and a sample MCP server is built to connect with the agent, demonstrating the capabilities of streaming and tool calling using a single chat bot.
See [README](./examples/sim_chat_demo/README.md)

#### Simple BEM typical building Network
This example is the prototype of BEM-AI, which consists of multiple agents collaboratively completing a building energy modeling task together.
See [README](./examples/sim_bem_network/README.md)

### EnergyPlus Chatbot with EnergyPlus MCP server
This example shows automa-ai integrates with EnergyPlus MCP, developed by LBNL.
See [README](./examples/eplus_mcp_demo/README.md)


## 🔍 Development Guidelines

### Code Organization
TBD

### Dependency Management
- Use `uv add <package>` to add new dependencies
- Update `uv.lock` with `uv lock` after dependency changes
- Keep dependencies minimal and focused

### Testing Strategy
TBD

## 🤝 Contributing
TBD

## 📄 License

see [LICENSE](/LICENSE.md)

---

**Note**: This project is experimental and under active development. Use in production environments is not recommended at this time.

## 📚 Citation

If you use this framework in your research or projects, please cite the following paper:

```bibtex
@article{xu5447218development,
  title={Development of a dynamic multi-agent network for building energy modeling: A case study towards scalable and autonomous energy modeling},
  author={Xu, Weili and Wan, Hanlong and Antonopoulos, Chrissi and Goel, Supriya},
  journal={Available at SSRN 5447218}
}
