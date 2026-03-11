# Default tools

Automa-AI supports first-class default tools configured directly in agent config (not MCP).

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
- `expected_outputs` (default `[]`)
- `timeout_s` (optional, capped by tool config)

Output format:
- `success`, `stdout`, `stderr`, `exit_code`
- `artifacts`: list of `{path, size_bytes, mime_type}`
- `meta`: `{runner, warnings}`

Configuration fields:
- `enabled` (default `true`)
- `runner` (default `local_subprocess`)
- `python_executable` (default `python`)
- `timeout_s` (default `20`)
- `max_stdout_chars`, `max_stderr_chars`
- `workspace_root`
- `allow_network`
- `allowed_imports`, `blocked_imports`
- `max_artifacts`, `max_artifact_bytes`

Sandbox limitations:
- Runs Python only with a local subprocess runner.
- Does not expose shell or bash execution.
- Rejects blocked imports and known dangerous call patterns before execution.
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
