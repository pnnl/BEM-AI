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
