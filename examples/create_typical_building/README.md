# Foundational Geometry Agent

This agent creates foundational building geometry models with ASHRAE-compliant construction sets. It generates default building geometries based on use type and applies appropriate envelope parameters based on climate zone and energy standards.

## Overview

The Foundational Geometry Agent provides the scaffolding for energy models by:
- Generating building geometries based on ASHRAE building types (Office, Hospital, School, Hotel, Retail, etc.)
- Applying ASHRAE 90.1 construction sets based on climate zone, building type, and standard version
- Creating OpenStudio Model (.osm) files ready for subsequent HVAC, lighting, and other building system modeling

## Current Status

✅ **Working**: A2A agent server with full MCP tool integration via SSE transport
✅ **Working**: OpenStudio geometry generation and construction set application tools
✅ **Working**: Single-command deployment with automatic MCP server lifecycle management

## Running the Agent

### Option 1: Interactive Streamlit UI (Recommended)

The easiest way to use the agent is through the Streamlit web interface:

```bash
# Terminal 1: Start the agent server
uv run python examples/create_typical_building/create_typical_building.py

# Terminal 2: Start the Streamlit UI
uv run streamlit run examples/create_typical_building/create_typical_building_ui.py
```

Then open your browser to the URL shown (typically `http://localhost:8501`).

**Features:**
- Interactive chat interface for building model creation
- Real-time streaming responses
- Visual feedback for tool calls and model generation
- No coding required - just natural language requests

### Option 2: Command Line (Programmatic)

```bash
uv run python examples/create_typical_building/create_typical_building.py
```

This single command will:
1. Start the MCP server on `http://localhost:8082` (SSE transport)
2. Start the A2A agent server on `http://localhost:8081`
3. Automatically connect the agent to the MCP tools

The servers will run until you type 'exit' or 'stop'.

## MCP Server Architecture

The OpenStudio tools are provided by an MCP server in `mcp_server/`. This server now uses **SSE (Server-Sent Events) transport over HTTP**, matching the pattern used by all other examples in the repository.

### Architecture Overview

**Current Implementation** (SSE Transport):
- MCP server runs as an embedded service started by the agent
- Communication via HTTP/SSE on `http://localhost:8082`
- Single command deployment
- Automatic lifecycle management
- Tools available via `@mcp.tool()` decorators

**Key Components**:
- `mcp_server/src/server.py`: FastMCP server with SSE transport
- `create_typical_building.py`: A2A agent that automatically starts and connects to MCP server
- `.env`: Configuration for both A2A and MCP server ports/hosts

### Available MCP Tools

1. `generate_default_ashrae_geometry_osm`: Load and save default building geometry
2. `generate_example_with_default_construction_set`: Generate geometry with ASHRAE construction set applied
3. `get_ashrae_enumeration_values`: List all available ASHRAE templates, building types, climate zones
4. `get_available_building_types`: List building types for geometry generation
5. `get_available_geometry_files`: List all geometry files in resources

## Agent Skills

The agent has two primary skills:

1. **Geometry Generation**: Generate default building geometries based on ASHRAE building types
2. **Construction and Envelope Configuration**: Apply ASHRAE 90.1 construction sets based on climate zone and standards

## Configuration

Edit `.env` to configure servers and LLM:

```env
# A2A Agent Server
CHATBOT_SERVER_URL=http://localhost:8081

# LLM Model Configuration
# See sample.env for all available model options (BIRTHRIGHT, Claude, OpenAI, Ollama)
# The chat model provider is auto-detected based on model name

# PNNL BIRTHRIGHT API (recommended for access to latest models)
BIRTHRIGHT_API=your-api-key
CHAT_BOT_MODEL_NAME=grok-4-fast-reasoning-birthright
CHAT_BOT_MODEL_BASE_URL=https://ai-incubator-api.pnnl.gov

# MCP Server (OpenStudio Tools)
CREATE_TYPICAL_BLDG_MCP_PORT=8082
CREATE_TYPICAL_BLDG_MCP_HOST=localhost

# Evaluation Judge Model (Ollama - default)
OLLAMA_MODEL_NAME=llama3.3:70b
OLLAMA_MODEL_BASE_URL=http://your-ollama-host:11434
```

**Supported Models:**
- **BIRTHRIGHT**: GROK, GPT-5, o3, o4-mini, Claude models via PNNL API
- **Claude**: Direct Anthropic API (Claude 3.5 Haiku/Sonnet, Claude 4)
- **OpenAI**: Direct OpenAI API (GPT-4o, GPT-4o-mini)
- **Ollama**: Local models (Llama, Qwen, Mistral)

The agent automatically detects the correct provider based on the model name.

**Evaluation Configuration:**

For automated evaluations using DeepEval, the default configuration uses **Ollama** as the LLM judge. This allows you to:
- Run evaluations on local infrastructure without API costs
- Use powerful open-source models like Llama 3.3 70B
- Maintain evaluation independence from cloud services

**Alternative: OpenAI for evaluation** - The code includes a commented-out section to use OpenAI's GPT models (like `gpt-4o-mini`) as the judge. To enable this, add `OPENAI_API_KEY` and `OPEN_AI_MODEL_NAME` to your `.env` and uncomment the relevant section in `create_typical_bldg_evaluation.py`.

## Testing the Agent

Three test utilities are provided to test different aspects of the system:

### Test Client (`test_client.py`)

Tests the A2A agent server end-to-end by sending natural language requests and streaming responses.

**Run the test client:**

```bash
# First, start the agent in one terminal
uv run python create_typical_building.py

# Then, in another terminal, run the test client
uv run python test_client.py
```

**What it tests:**

1. **Available building types**: Queries the agent for supported building types
2. **Climate zones**: Asks about supported ASHRAE climate zones
3. **Building model creation**: Requests creation of a small office building with specific parameters (ASHRAE 90.1-2013, climate zone 4A)

**Expected output**: The test client streams responses from the agent, displaying real-time status updates as the agent processes each request.

**Key features:**
- Uses `SimpleClient` from `automa_ai.client.simple_client`
- Demonstrates streaming message handling with A2A protocol
- Shows how to parse `status-update` events with text parts
- All requests use the same `context_id` to maintain conversation continuity

### Test MCP Tools (`test_mcp_tools.py`)

Tests the MCP server tools directly via SSE transport, bypassing the agent layer.

**Run the MCP tools test:**

```bash
# First, start the agent (which also starts the MCP server)
uv run python create_typical_building.py

# Then, in another terminal, test the MCP server directly
uv run python test_mcp_tools.py
```

**What it tests:**

1. **List tools**: Enumerates all available MCP tools with their schemas
2. **List resources**: Shows available resources exposed by the MCP server
3. **get_available_building_types**: Calls the tool to retrieve building type enumerations
4. **get_ashrae_enumeration_values**: Retrieves ASHRAE templates, climate zones, and building types
5. **generate_default_ashrae_geometry_osm**: Creates a SmallOffice geometry and saves it to `/tmp/mcp_test`

**Expected output**: The test displays:
- Complete tool registry with input schemas
- Available resources
- JSON responses from each tool invocation
- File path confirmation for generated geometry

**Key features:**
- Uses MCP Python SDK (`mcp.client.sse`, `mcp.ClientSession`)
- Connects via SSE transport to `http://localhost:8082/sse`
- Shows low-level MCP protocol interaction
- Useful for debugging MCP server issues independently of the agent

### Automated Evaluation (`evaluation/create_typical_bldg_evaluation.py`)

Evaluates agent performance using [DeepEval](https://github.com/confident-ai/deepeval) metrics with LLM-as-a-judge scoring.

**Setup:**

1. **Configure evaluation model** (add to `.env`):
   
   By default, the evaluation uses **Ollama** for the judge model:
   ```env
   # Ollama (default for evaluation)
   OLLAMA_MODEL_NAME=llama3.3:70b
   OLLAMA_MODEL_BASE_URL=http://your-ollama-host:11434
   ```

   **Alternative: OpenAI GPT** (commented out in code, uncomment to use):
   ```env
   # OpenAI API (alternative - requires code modification)
   OPENAI_API_KEY=sk-proj-your-key-here
   OPEN_AI_MODEL_NAME=gpt-4o-mini
   ```
   
   To switch to OpenAI, uncomment lines 268-273 and comment out lines 261-265 in `create_typical_bldg_evaluation.py`.

2. **Run the evaluation:**
   ```bash
   uv run python examples/create_typical_building/evaluation/create_typical_bldg_evaluation.py
   ```

**What it evaluates:**

The test suite in `evaluation/create_typical_bldg_test_data.json` contains scenarios covering:

1. **Information gathering**: Agent asks for missing climate zone before making tool calls
2. **Tool selection**: Correct tools are invoked with properly formatted parameters
3. **Climate zone formatting**: Validates ASHRAE 169-2013-<zone> format compliance
4. **Building type validation**: Agent verifies building types and suggests alternatives for invalid requests
5. **Default handling**: Agent explicitly informs users when defaulting to ASHRAE 90.1-2013 standard

**Metrics:**

- **Tool Correctness** (ToolCorrectnessMetric): Evaluates whether the agent selected and called the right tools
  - Tool calling: Did the expected tools get called?
  - Tool selection: Were the chosen tools appropriate for the task?
  
- **Correctness** (GEval): Custom evaluator for domain-specific behaviors
  - Climate zone formatting (ASHRAE 169-2013-<zone>)
  - Clarification behavior (asking for missing information)
  - Tool usage alignment with expected output

**Judge Model:**

The evaluation uses an **Ollama model** (default: `llama3.3:70b`) as the judge. The judge model is configured separately from the agent model, allowing you to:
- Use Ollama for evaluation while running the agent with BIRTHRIGHT/Claude/OpenAI
- Run evaluations on local infrastructure
- Switch to OpenAI GPT models by modifying the code (commented section provided)

**Output:**

Results are saved to `evaluation/create_typical_bldg_evaluation_output.json` with:
- Question/expected/actual output for each test case
- Per-metric scores and pass/fail status
- Detailed reasoning from the judge model
- Verbose logs for debugging failures

**Example output structure:**
```json
{
  "question": "Create a medium office building and save it to /tmp/models",
  "expected": "Agent asks for climate zone before proceeding...",
  "actual_output": "What climate zone should I use...",
  "deepeval_result": {
    "passed": true,
    "metrics_data": [
      {
        "metric": "Tool Correctness",
        "passed": true,
        "score": 1.0,
        "reason": "...",
        "verbose_logs": {...}
      }
    ]
  }
}
```

### Testing Workflow

**Recommended testing sequence:**

1. **Verify MCP server**: Run `test_mcp_tools.py` to ensure all tools are working correctly
2. **Test agent integration**: Run `test_client.py` to verify the agent can orchestrate MCP tools
3. **Run automated evaluation**: Execute the evaluation suite to measure agent performance
4. **Manual testing**: Send custom A2A requests via the SimpleClient or API calls

**Common testing scenarios:**

```python
# Example natural language requests for the agent:
"What building types are available for geometry generation?"
"List all climate zones"
"Create a medium office building with ASHRAE 90.1-2013 constructions for climate zone 4A and save it to /tmp/models"
"Generate a primary school geometry and apply 90.1-2016 envelope for zone 5A, save to ~/Documents/models"
```

## Architecture Details

### Component Interaction

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────────┐
│  Streamlit UI   │ A2A     │  Agent Server    │  SSE    │  MCP Server         │
│  or Test Client │────────▶│  (port 8081)     │────────▶│  (port 8082)        │
└─────────────────┘         └──────────────────┘         └─────────────────────┘
                                    │                              │
                            Uses LangGraph Agent              FastMCP Server
                            with tool-calling             (OpenStudio Standards)
```

### Files Overview

| File | Purpose |
|------|---------|
| `create_typical_building.py` | Main entry point - starts both A2A and MCP servers |
| `create_typical_building_ui.py` | Streamlit web interface for interactive chat |
| `test_client.py` | A2A client test - tests agent through natural language |
| `test_mcp_tools.py` | Direct MCP test - tests MCP tools without agent layer |
| `evaluation/create_typical_bldg_evaluation.py` | Automated DeepEval test suite with LLM-as-a-judge |
| `evaluation/create_typical_bldg_test_data.json` | Test cases and expected outputs for evaluation |
| `evaluation/create_typical_bldg_evaluation_output.json` | Evaluation results with scores and detailed logs |
| `mcp_server/src/server.py` | FastMCP server with OpenStudio Standards tools |
| `.env` | Configuration for ports, hosts, and LLM settings |
| `sample.env` | Template .env file with all configuration options |

## Troubleshooting

**Agent not responding:**
- Verify both servers started successfully (check terminal output)
- Test MCP server directly with `test_mcp_tools.py`
- Check `.env` configuration for correct ports and URLs

**MCP tools not available:**
- Ensure MCP server started on port 8082 (check logs)
- Verify SSE endpoint is accessible: `curl http://localhost:8082/sse`
- Review MCP server logs for initialization errors

**Model generation fails:**
- Check that the save directory exists or can be created
- Verify OpenStudio Standards library is accessible
- Review tool invocation logs in the agent debug output

## Next Steps

1. ~~Implement stdio client support~~ ✅ (Converted to SSE transport instead)
2. ~~Convert MCP server to SSE~~ ✅ (Completed)
3. ~~Add test utilities~~ ✅ (Completed)
4. ~~Add chatbot interface~~ ✅ (Streamlit UI completed)
5. ~~Implement automated evaluation framework~~ ✅ (DeepEval integration completed)
6. **Create SME use cases** - to drive development and testing of MCP tools (in-progress)
7. **Expand evaluation test suite** - add more edge cases and domain-specific scenarios, add substantially more tools.

## Example Usage

Once the agent is running, it can handle requests like:
- "Create a medium office building with ASHRAE 90.1-2013 constructions for climate zone 4A"
- "Generate geometry for a primary school and save to /tmp/models"
- "Apply construction sets for a retail building in zone 5B"

The agent returns structured responses with:
- Status (`input_required`, `completed`, or `error`)
- Building parameters (type, climate zone, standard)
- Output file path
- Error details if applicable

