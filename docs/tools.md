# Tools

Automa-AI supports two types of tools:
1. **Built-in tools** - Framework-provided tools like `web_search`
2. **Custom tools** - User-defined tools using `@tool` decorator

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
- Rejects blocked imports and known dangerous call patterns before execution.
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
        - os
        - subprocess
        - socket
        - requests
        - urllib
        - ctypes
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
