# BEM A2A - Multi-Agent Network Project

A multi-agent network system built on Google's A2A (Agent-to-Agent) and Anthropic's MCP (Model Context Protocol) protocols, combining the power of LangChain, Google GenAI, and modern agent orchestration.

## ⚠️ Project Status

This project is in its **early development phase** and is considered **highly unstable**. APIs, interfaces, and core functionality are subject to significant changes. Use for development and experimentation only.

## 🚀 Overview

BEM A2A creates a distributed multi-agent system that enables intelligent agents to communicate, collaborate, and coordinate using industry-standard protocols. The system leverages:

- **Google A2A Protocol**: For agent-to-agent communication
- **Anthropic MCP Protocol**: For model context management
- **LangChain**: For agent orchestration and workflow management
- **Google GenAI**: For AI model integration

## 🛠️ Technology Stack

### Core Dependencies
- **LangChain**: Agent framework and orchestration
- **Google GenAI**: AI model integration
- **Google A2A**: Agent-to-agent communication protocol
- **Anthropic MCP**: Model context protocol implementation

### Development Tools
- **uv**: Modern Python package management
- **Python 3.12**: Runtime environment

## 📁 Project Structure

```
BEM-AI/
├── examples/                           # Example applications built with the foundational framework
├── src/
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
│   └── prompt_engineering/             # Under development
├── pyproject.toml                      # Project configuration
├── uv.lock                             # Dependency lock file
└── README.md                           # This file
```

## 🔧 Installation

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd bem_a2a
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
- **Tool and Resources**: External tool and resource access through MCPs.

## 📝 Configuration

Project configuration is managed through `pyproject.toml`. Key configuration areas include:

- **Dependencies**: Core and development packages
- **Build System**: uv-based build configuration
- **Project Metadata**: Version, description, and author information

## Examples
#### Simple BEM typical building Network

<img src="sources/bem-agentic.png" alt="BEM-Agents" width="400">

To run this example, the user will need to provide your own language models when creating agents
```python
planner = AgentFactory(
    card=agent_card,
    instructions=PLANNER_COT,
    model_name="llama3.3:70b", # need to replace this model to a user accessible language model
    agent_type=GenericAgentType.LANGGRAPH,
    chat_model=GenericLLM.OLLAMA,
    response_format=ResponseFormat,
    model_base_url="http://rc-chat.pnl.gov:11434" # if needed, provide the base URL.
)
```
It is recommended using a large size model, for example, llama3.3:70b for planner agent and use reasoning models such as qwen3:4b for the specialized agents.
You can run the simple BEM agentic AI on the commandline:
```shell
~ BEM-AI > PYTHONPATH=/[YOUR DIRECTORY]/BEM-AI/automa_ai [YOUR PATH]/BEM-AI/.venv/bin/python [YOUR PATH]/BEM-AI/examples/simple_bem_network/sim_bem_network_app.py
```
If successful,  you should be able to see this message in your command line
```bash

    🛠️  🏢  🏗️  ╔════════════════════════╗
    🟢           B E M - A I           
    🛡️  ⚡  💡  ╚════════════════════════╝
    
🛠️ Thank you for using BEM-AI! I am your assistant to help analyze building performance 🏢
💡 You can ask questions such as:
   • 🔹 What is the energy savings from reducing window-to-wall ratio by 10%?
   • 🔹 Create an energy model for a new office.

✍️ Your question: 
```

Type your BEM tasks such as:
```bash
✍️ Your question: I have a model in local directory: /Users/[User Name]/ai/experiment/baseline.osm, I want to evaluate the energy savings by adding daylighting sensors
```


See Live Demo of BEM-AI on [Youtube](https://youtu.be/eYhvig792Sc).

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