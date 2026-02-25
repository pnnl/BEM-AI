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
5. `get_available_space_types`: List available space types
6. `get_available_geometry_files`: List all geometry files in resources

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
```

**Supported Models:**
- **BIRTHRIGHT**: GROK, GPT-5, o3, o4-mini, Claude models via PNNL API
- **Claude**: Direct Anthropic API (Claude 3.5 Haiku/Sonnet, Claude 4)
- **OpenAI**: Direct OpenAI API (GPT-4o, GPT-4o-mini)
- **Ollama**: Local models (Llama, Qwen, Mistral)

The agent automatically detects the correct provider based on the model name.

## Testing the Agent

Two test utilities are provided to test different aspects of the system:

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

### Testing Workflow

**Recommended testing sequence:**

1. **Verify MCP server**: Run `test_mcp_tools.py` to ensure all tools are working correctly
2. **Test agent integration**: Run `test_client.py` to verify the agent can orchestrate MCP tools
3. **Manual testing**: Send custom A2A requests via the SimpleClient or API calls

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
| `mcp_server/src/server.py` | FastMCP server with OpenStudio Standards tools |
| `.env` | Configuration for ports, hosts, and LLM settings |

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
5. **Create SME use cases** - to drive development and testing of MCP tools (in-progress)

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

