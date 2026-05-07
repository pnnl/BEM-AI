# Headless YAML Subagent Demo

This example shows a coordinator agent using the built-in `yaml_agent` tool to
create an ephemeral headless subagent from a YAML file, execute one focused
analysis task, stream progress, return the result, and close the subagent.

The scenario is intentionally small:

- The coordinator receives a request to analyze monthly simulation results.
- The coordinator reports a focused progress update such as
  "Computing annual totals from the monthly results..."
- The coordinator calls `yaml_agent` with
  `subagents/energy_results_analyst.yaml`.
- The headless analyst uses only the built-in `run_python` tool to read
  `data/monthly_results.csv` and compute summary metrics.
- No A2A subagent server is started.

## Files

- `coordinator.yaml`: parent agent spec. It enables only the `yaml_agent` tool.
- `prompts/coordinator.md`: parent instruction that says when to spawn the
  headless analyst and how to scope the delegated query.
- `subagents/energy_results_analyst.yaml`: constrained headless subagent spec.
- `prompts/energy_results_analyst.md`: specialist analysis instruction.
- `data/monthly_results.csv`: sample monthly energy results.
- `run_demo.py`: local runner that streams the coordinator response.

## Run

From the repository root:

```bash
ollama pull llama3.1:8b
python3 examples/headless_yaml_subagent_demo/run_demo.py
```

Override the model endpoint with `OLLAMA_HOST` if needed:

```bash
OLLAMA_HOST=http://localhost:11434 python3 examples/headless_yaml_subagent_demo/run_demo.py
```

You can also pass a custom query:

```bash
python3 examples/headless_yaml_subagent_demo/run_demo.py "Analyze the monthly results and report annual electricity, peak demand, and missing months."
```

## Why This Example Matters

This is different from normal A2A delegation. The analyst is not a running
server. It is created on demand from YAML by the parent agent's tool call, used
for one scoped task, and closed immediately afterward.

The subagent spec follows the constrained template:

- no MCP configuration;
- no persistent memory or custom memory store;
- no nested subagents;
- no `yaml_agent` tool inside the subagent;
- only built-in default tools when needed.
