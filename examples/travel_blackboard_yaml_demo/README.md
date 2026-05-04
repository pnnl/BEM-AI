# YAML Travel Booking Blackboard Demo

This example mirrors `examples/travel_blackboard_demo` but defines the agents
with YAML specs instead of constructing each `AgentFactory` directly in Python.

The runtime behavior is the same:

- Four A2A agents are started: orchestrator, flight, hotel, and car.
- All agents share the same local JSON blackboard.
- Travel quote and booking tools are deterministic mock providers.
- The orchestrator delegates to A2A subagents through `SubAgentSpec`.

## Agents

- `TravelOrchestratorAgent` (`http://localhost:33000/`)
- `TravelFlightAgent` (`http://localhost:33001/`)
- `TravelHotelAgent` (`http://localhost:33002/`)
- `TravelCarAgent` (`http://localhost:33003/`)

## What is YAML-defined

Each file under `specs/` defines one agent:

- `specs/orchestrator_agent.yaml`
- `specs/flight_agent.yaml`
- `specs/hotel_agent.yaml`
- `specs/car_agent.yaml`

The YAML specs define:

- A2A 1.0 `agent_card` metadata with `supportedInterfaces`.
- File-backed instructions under `prompts/`.
- Model provider and model name.
- Runtime settings.
- Tool configuration for specialist agents.
- Subagent delegation configuration for the orchestrator.

`multi_agent.py` still performs demo-only runtime setup:

- Registers the local deterministic travel tools.
- Loads the shared blackboard schema once.
- Injects the same blackboard config into all four loaded specs.
- Applies `OLLAMA_HOST` as the model base URL.
- Starts the resulting A2A servers with `A2AServerManager`.

## Setup

### 1) Install Ollama and pull model

```bash
ollama pull llama3.1:8b
```

By default the demo targets `http://localhost:11434`. Override with `OLLAMA_HOST`
if needed.

### 2) Install Python dependencies

From repository root, install the project and dependencies as you normally do for
AUTOMA-AI.

## Run

In one terminal:

```bash
python3 examples/travel_blackboard_yaml_demo/multi_agent.py
```

In a second terminal:

```bash
streamlit run examples/travel_blackboard_yaml_demo/ui.py
```

## Example prompts

- "Plan a trip from Seattle to Denver departing 2026-06-10 and returning 2026-06-13 with a budget of 1500."
- "Yes, confirm requirements and fetch quotes."
- "Select flight 1, hotel 2, car 1."
- "Book this itinerary."
- "Change destination to Austin and keep dates the same."

## Testing

Run the lightweight scripted scenario test:

```bash
pytest examples/travel_blackboard_yaml_demo/tests -q
```

Run the YAML spec loader tests:

```bash
pytest tests/test_yaml_agent_spec.py -q
```

## Troubleshooting

- **Ollama not running / model missing**: Start Ollama and run `ollama pull llama3.1:8b`.
- **Ports already in use**: Update ports in `specs/*_agent.yaml` and `ui.py`.
- **Blackboard path permissions**: Ensure write access to `examples/travel_blackboard_yaml_demo/.demo_blackboards/`.
