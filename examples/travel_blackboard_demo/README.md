# Travel Booking Blackboard Demo

This example demonstrates **multi-agent blackboard orchestration** in AUTOMA-AI using the same production pattern:

- `AgentFactory` constructs every agent (orchestrator + subagents).
- Runtime execution is handled by `GenericLangGraphChatAgent`.
- A shared session blackboard is configured once and propagated to all agents.
- The orchestrator delegates to A2A subagents instead of calling Python functions directly.

## Agents

- `TravelOrchestratorAgent` (`http://localhost:33000/`)
- `TravelFlightAgent` (`http://localhost:33001/`)
- `TravelHotelAgent` (`http://localhost:33002/`)
- `TravelCarAgent` (`http://localhost:33003/`)

## What this demonstrates

1. Blackboard config path: `example config -> AgentFactory -> langgraph_chatagent`.
2. Blackboard tools available to all agents:
   - `blackboard_read`
   - `blackboard_write`
   - `blackboard_get_revision`
3. Orchestrator delegation to subagents through `SubAgentSpec` tool connectivity.
4. Deterministic mock quote providers and confirmation IDs.
5. Quote staleness handling when requirements change.

## Setup

### 1) Install Ollama and pull model

```bash
ollama pull llama3.1:8b
```

By default the demo targets `http://localhost:11434`. Override with `OLLAMA_HOST` if needed.

### 2) Install Python dependencies

From repository root, install the project and dependencies as you normally do for AUTOMA-AI.

## Run

In one terminal:

```bash
python3 examples/travel_blackboard_demo/multi_agent.py
```

In a second terminal:

```bash
streamlit run examples/travel_blackboard_demo/ui.py
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
pytest examples/travel_blackboard_demo/tests -q
```

## Troubleshooting

- **Ollama not running / model missing**: Start Ollama and run `ollama pull llama3.1:8b`.
- **Ports already in use**: Update ports in `agents/*_card.json` and `ui.py`.
- **Blackboard path permissions**: Ensure write access to `examples/travel_blackboard_demo/.demo_blackboards/`.
