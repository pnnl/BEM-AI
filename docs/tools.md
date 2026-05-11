# Tools

Automa-AI supports two types of tools:
1. **Built-in tools** - Framework-provided tools like `web_search`
2. **Custom tools** - User-defined tools using `@tool` decorator

> **Important:** Built-in tools are **not automatically available**. They, along with custom tools, must be explicitly enabled by the user through `tools_config`. If a tool is not included in the configuration, the agent will not be able to use it.

## Configuration format

```yaml
tools:
  - type: web_search
    config:
      provider: serper # auto|serper|opensource
      serper:
        api_key: ${SERPER_API_KEY}
      firecrawl:
        api_key: ${FIRECRAWL_API_KEY}
        enabled: true
      scrape:
        enabled: true
        max_pages: 5
      rerank:
        provider: jina # jina|cohere|opensource|none
        top_k: 5
        jina_api_key: ${JINA_API_KEY}
```

`AgentFactory` accepts `tools_config` as:
- `ToolsConfig`
- a dict with a `tools` list
- a plain list of tool specs.

## Built-in tool: `web_search`

> ⚠️ This tool must be explicitly enabled in `tools_config` to be used.

Input fields:
- `query` (required)
- `top_k` (default `5`)
- `max_results` (default `10`)
- `time_range`, `language`, `region` (optional)
- `scrape` (default `true`)
- `include_raw_content` (default `false`)

Output format:
- `results`: list of `{title, url, snippet, content?, score?, source}`
- `meta`: `{provider_used, reranker_used, timings, warnings}`


## Built-in tool: `run_python`

> ⚠️ This tool must be explicitly enabled in `tools_config` to be used.

Input fields:
- `code` (required)
- `input_files` (default `[]`)
- `expected_outputs` (default `[]`; if omitted, only files newly created/modified by execution are returned)
- `timeout_s` (optional, capped by tool config)

Output format:
- `success`, `stdout`, `stderr`, `exit_code`
- `artifacts`: list of `{path, size_bytes, mime_type}`
- `meta`: `{runner, warnings}`

Configuration fields:
- `runner` (default `local_subprocess`)
- `python_executable` (default `python`)
- `timeout_s` (default `20`)
- `max_stdout_chars`, `max_stderr_chars`
- `workspace_root`
- `allow_network` (controls import-policy checks only; it is not runtime network isolation)
- `allowed_imports`, `blocked_imports`
- `max_artifacts`, `max_artifact_bytes`

Sandbox limitations:
- Runs Python only with a local subprocess runner.
- Uses best-effort static policy checks; it is not a hardened sandbox for untrusted code.
- Does not expose shell or bash execution.
- Allows normal local-file helpers such as `os` and `pathlib`, but rejects blocked imports and known dangerous call patterns before execution.
- Blocks subprocess execution, shell execution, and network imports by default.
- Rejects reserved startup file names (`sitecustomize.py`, `usercustomize.py`, and `.pth`) in `input_files`.
- Enforces timeout and output truncation.
- Executes code in a temporary working directory and only returns files from that directory.

Example config:

```yaml
tools:
  - type: run_python
    config:
      runner: local_subprocess
      timeout_s: 20
      workspace_root: .
      allow_network: false
      blocked_imports:
        - subprocess
        - socket
        - requests
        - urllib
        - ctypes
```

## Built-in tool: `yaml_agent`

> ⚠️ This tool must be explicitly enabled in `tools_config` to be used.

The `yaml_agent` tool creates an AUTOMA-AI agent from a YAML spec using
`load_agent_factory_from_yaml(...)`, executes a query through the created agent,
and returns the streamed chunks plus the final response. When called from a
streaming AUTOMA-AI parent agent, intermediate chunks are emitted through the
parent stream so users can see progress while the YAML-defined agent runs.

For delegated headless subagents, start from
`docs/templates/headless_subagent.yaml`. Keep those YAML specs constrained:
enable only built-in default tools such as `web_search` or `run_python` when
needed, do not enable `yaml_agent` inside the subagent, and do not add MCP,
persistent memory, or nested subagent configuration.

Parent agents should be instructed to spawn these headless subagents when a
focused task appears, for example: "Computing annual totals from the monthly
results..." followed by a `yaml_agent` call whose `query` tells the subagent
which file to read, which metrics to compute, and what output format to return.

Input fields:
- `yaml_path` (required): path to the YAML agent spec.
- `query` (required): task or question for the YAML-defined agent.
- `context_id`, `task_id`, `user_id`, `metadata` (optional): runtime context
  passed to the created agent.

Output format:
- `final`: final response text.
- `chunks`: streamed text chunks collected while the agent ran.
- `context_id`, `task_id`
- `requires_user_input`: whether the run ended by asking the user for input.

Configuration fields:
- `base_dir` (optional): base directory for resolving relative `yaml_path`
  values. When set, `yaml_agent` only accepts specs that resolve inside this
  directory.

Before creating the agent, `yaml_agent` validates the target spec against the
headless-subagent constraints: no MCP, no memory config, no persistent
checkpointer, no nested subagents, no `yaml_agent` tool, and no custom tools.

Example config:

```yaml
tools:
  - type: yaml_agent
    config:
      base_dir: ./agents
```

## Provider behavior

- Search providers:
  - `serper` when configured with an API key.
  - Open-source fallback via `duckduckgo_search`.
- Scraping providers:
  - Firecrawl when key is configured and scraping is enabled.
  - Open-source fallback using `httpx` + `trafilatura` (BeautifulSoup fallback).
- Rerank providers:
  - Jina, Cohere, or open-source BM25 fallback.
  - On rerank failure, original order is returned with warnings.

## Installation

```bash
pip install -e .[web]
```

Optional local embedding rerank helpers:

```bash
pip install -e .[rerank]
```

---

## Custom Tools

Define your own tools using the `@tool` decorator. Tools are automatically registered and can be used in agent config.

### Basic usage

```python
# myapp/tools.py
from automa_ai.tools import tool

@tool
def repeat_text(text: str, count: int = 1) -> str:
    """Repeat text multiple times.
    
    Args:
        text: Text to repeat
        count: Number of times
    """
    return text * count
```

Reference in config using dotted path:

```yaml
tools:
  - type: myapp.tools.repeat_text
    config: {}
```

The framework will auto-import `myapp.tools`, triggering the decorator and registering the tool.

### Async tools

```python
@tool
async def fetch_data(url: str) -> dict:
    """Fetch data from URL.
    
    Args:
        url: URL to fetch
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return {"data": response.json()}
```

### Tools with configuration

For tools requiring API keys or settings:

```python
from pydantic import BaseModel

class SearchConfig(BaseModel):
    api_key: str
    endpoint: str = "https://api.example.com"

@tool(config_schema=SearchConfig)
def search(query: str, *, config: SearchConfig) -> dict:
    """Search using configured API.
    
    Args:
        query: Search query
    """
    # Config is injected automatically
    return call_api(query, config.api_key, config.endpoint)
```

Config in YAML:

```yaml
tools:
  - type: myapp.tools.search
    config:
      api_key: ${SEARCH_API_KEY}
      endpoint: "https://custom.api.com"
```

### Custom name and description

```python
@tool(name="web_search", description="Search the web")
def my_search_tool(query: str) -> dict:
    """This docstring is overridden by description parameter."""
    return {"results": [...]}
```

### Features

- **Schema inference**: Automatically generates Pydantic schemas from type hints
- **Docstring parsing**: Extracts parameter descriptions from Google-style docstrings
- **Config injection**: Pass configuration at instantiation time
- **Auto-import**: Tools are imported automatically based on config `type` field
- **Sync/async**: Both sync and async functions supported
