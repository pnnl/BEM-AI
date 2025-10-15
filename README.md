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
bem_a2a/
├── src/
│   ├── agent_card/           # All agent cards goes to here
│   ├── agent_test/           # Test implementations and examples
│   │   ├── run_orchestration_test.py  # Primary test runner
│   │   └── ...               # Additional test files
│   ├── agents/               # Generic agent classes
│   ├── bem_mcp/              # MCP servers for the BEM.
│   ├── client/               # Test implementations and examples
│   ├── common/               # Util files or shared resources.
│   └── prompt_engineering/   # Prompt engineering
├── pyproject.toml            # Project configuration
├── uv.lock                   # Dependency lock file
└── README.md                 # This file
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

The primary test suite is located in `src/agent_test/` with the main test runner being `run_orchestration_test.py`.

### Execute Main Test Suite
```bash
uv run src/agent_test/run_orchestration_test.py
```

### Development Testing
```bash
# Run with uv
uv run python src/agent_test/run_orchestration_test.py

# Or activate shell first
uv shell
python src/agent_test/run_orchestration_test.py
```

## 🏗️ Architecture

### Multi-Agent System Design
The system implements a distributed architecture where:

1. **Agents** communicate using Google's A2A protocol
2. **Context** is managed through Anthropic's MCP protocol
3. **Orchestration** is handled by LangChain frameworks
4. **AI Models** are integrated via Google GenAI

### Key Components
- **Agent Network**: Distributed agent communication layer
- **Context Manager**: MCP-based context sharing and management
- **Orchestrator**: LangChain-based workflow coordination
- **Model Interface**: Google GenAI integration layer

## 📝 Configuration

Project configuration is managed through `pyproject.toml`. Key configuration areas include:

- **Dependencies**: Core and development packages
- **Build System**: uv-based build configuration
- **Project Metadata**: Version, description, and author information

## Examples
#### Simple BEM typical building Network

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

## 🔍 Development Guidelines

### Code Organization
- Place test code in `src/agent_test/`
- Use `run_orchestration_test.py` as the primary test entry point
- Follow the existing project structure for new components

### Dependency Management
- Use `uv add <package>` to add new dependencies
- Update `uv.lock` with `uv lock` after dependency changes
- Keep dependencies minimal and focused

### Testing Strategy
- Focus testing efforts on `run_orchestration_test.py`
- Test agent communication protocols thoroughly
- Validate context management and sharing
- Ensure orchestration workflows function correctly

## 🚨 Known Limitations

- **Stability**: Core functionality is under active development
- **API Changes**: Interfaces may change without notice
- **Documentation**: Limited due to early development stage
- **Error Handling**: May be incomplete or inconsistent

## 🤝 Contributing

Since this project is in early development:

1. **Fork** the repository
2. **Create** a feature branch
3. **Test** thoroughly using `run_orchestration_test.py`
4. **Submit** a pull request with detailed description

## 📄 License

[License information to be added]

## 📞 Support

For development questions and issues:
- Review test implementations in `src/agent_test/`
- Check `run_orchestration_test.py` for usage examples
- Examine `pyproject.toml` for configuration details

## 🔮 Roadmap

- [ ] Stabilize core agent communication protocols
- [ ] Improve MCP context management
- [ ] Enhanced error handling and logging
- [ ] Comprehensive documentation
- [ ] Production-ready deployment options
- [ ] Performance optimization
- [ ] Extended test coverage

---

**Note**: This project is experimental and under active development. Use in production environments is not recommended at this time.