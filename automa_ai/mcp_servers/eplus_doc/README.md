# EnergyPlus Documentation Search FastMCP Server

This FastMCP (Fast Model Context Protocol) server provides specialized search tools for the EnergyPlus Input/Output Reference documentation hosted at `https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/` using Server-Sent Events (SSE) transport.

## Features

- **FastMCP Framework**: Built with modern FastMCP for better performance and maintainability
- **SSE Transport**: Uses Server-Sent Events for real-time communication
- **Focused Search**: Search specifically within the EnergyPlus documentation domain
- **Intelligent Caching**: Pages are cached for 24 hours to improve performance
- **Content Discovery**: Automatically discovers and maps the documentation structure
- **Relevance Scoring**: Results are ranked by relevance to your query
- **Structured JSON Responses**: All responses are well-formatted JSON for easy parsing
- **Health Monitoring**: Built-in health check and monitoring endpoints

## Installation

1. **Install Dependencies**:
```bash
pip install -r requirements.txt
```

2. **Start the Server**:
```bash
# Using the startup script (recommended)
python startup.py

# Or directly with uvicorn
uvicorn energyplus_docs_fastmcp:app --host 127.0.0.1 --port 8000

# For development with auto-reload
python startup.py --reload --log-level DEBUG
```

3. **Configure MCP Client**: Add the server configuration to your MCP client configuration file:
```json
{
  "mcpServers": {
    "energyplus-docs-search": {
      "command": "python",
      "args": ["-m", "uvicorn", "energyplus_docs_fastmcp:app", "--host", "127.0.0.1", "--port", "8000"],
      "transport": {
        "type": "sse",
        "url": "http://127.0.0.1:8000/sse"
      }
    }
  }
}
```

## Server Endpoints

- **Main Server**: `http://127.0.0.1:8000/`
- **SSE Endpoint**: `http://127.0.0.1:8000/sse` (for MCP client connections)
- **Health Check**: `http://127.0.0.1:8000/health`

## Available Tools

### 1. `search_energyplus_docs`
Search through the EnergyPlus documentation with intelligent ranking.

**Parameters**:
```python
class SearchQuery(BaseModel):
    query: str  # Required: Search terms
    max_results: int = 10  # Optional: Max results (1-50)
```

**Example Request**:
```json
{
  "query": "zone air temperature",
  "max_results": 5
}
```

**Example Response**:
```json
{
  "query": "zone air temperature",
  "total_results": 5,
  "results": [
    {
      "rank": 1,
      "title": "Zone Air Temperature Controls",
      "section": "Zone HVAC Controls",
      "url": "https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/...",
      "relevance_score": 45.2,
      "preview": "Zone air temperature is controlled by..."
    }
  ]
}
```

### 2. `get_page_details`
Get comprehensive information about a specific documentation page.

**Parameters**:
```python
class PageDetailsQuery(BaseModel):
    url: str  # Required: Full URL of the documentation page
```

**Example Request**:
```json
{
  "url": "https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-hvac-design-objects.html"
}
```

**Example Response**:
```json
{
  "page_info": {
    "title": "Group – HVAC Design Objects",
    "section": "HVAC Design Objects",
    "url": "https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-hvac-design-objects.html",
    "word_count": 2543,
    "last_updated": "2024-01-15T10:30:00"
  },
  "content_preview": "This section describes the HVAC design objects..."
}
```

### 3. `discover_documentation_structure`
Map out the structure of the EnergyPlus documentation site.

**Parameters**:
```python
class DiscoveryQuery(BaseModel):
    max_pages: int = 100  # Optional: Max pages to discover (10-500)
```

**Example Response**:
```json
{
  "discovery_info": {
    "total_pages": 156,
    "total_sections": 12,
    "base_url": "https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/"
  },
  "sections": {
    "Zone HVAC Controls": {
      "page_count": 15,
      "pages": [
        {
          "name": "thermostats.html",
          "url": "https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/thermostats.html"
        }
      ]
    }
  }
}
```

## Usage Examples

### Using with MCP Client
Once configured, you can use the tools through any MCP-compatible client:

```python
# Search for HVAC-related content
result = await mcp_client.call_tool(
    "search_energyplus_docs", 
    {
        "query": "HVAC system sizing",
        "max_results": 10
    }
)

# Get details about a specific page
result = await mcp_client.call_tool(
    "get_page_details",
    {
        "url": "https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-zone-hvac-controls-and-thermostats.html"
    }
)

# Discover documentation structure
result = await mcp_client.call_tool(
    "discover_documentation_structure",
    {"max_pages": 150}
)
```

### Direct HTTP API Testing
You can also test the server directly using HTTP requests:

```bash
# Check server health
curl http://127.0.0.1:8000/health

# Server info
curl http://127.0.0.1:8000/
```

## FastMCP vs Traditional MCP

This implementation uses FastMCP which provides several advantages:

### FastMCP Benefits:
- **Modern Python**: Built with FastAPI, Pydantic, and async/await
- **Better Performance**: Optimized for high-throughput scenarios
- **Type Safety**: Full Pydantic validation for all inputs/outputs
- **SSE Transport**: Real-time bidirectional communication
- **Auto-documentation**: Built-in API docs and OpenAPI schema
- **Easy Testing**: Standard HTTP endpoints for debugging
- **Health Monitoring**: Built-in health checks and metrics

### SSE Transport Advantages:
- **Real-time Updates**: Server can push updates to clients
- **Better Connection Management**: More resilient than polling
- **Lower Latency**: Immediate response delivery
- **Web Standards**: Works with standard HTTP infrastructureHVAC system sizing"}
)
```

### Get Specific Page Details
```python
# Get details about a specific page
result = await mcp_client.call_tool(
    "get_page_details",
    {"url": "https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-zone-hvac-controls-and-thermostats.html"}
)
```

### Discover Documentation Structure
```python
# Map the documentation structure
result = await mcp_client.call_tool(
    "discover_documentation_structure",
    {"max_pages": 150}
)
```

## Technical Details

### Caching Strategy
- Pages are cached in memory for 24 hours
- Automatic cache invalidation and refresh
- Reduces load on the target website while maintaining fresh content

### Search Algorithm
The search uses a weighted scoring system:
- **Title matches**: 10x weight
- **Content matches**: 1x weight  
- **Exact phrase bonus**: +5 points
- Results sorted by relevance score

### Content Extraction
- Extracts meaningful content from HTML (paragraphs, headings, lists, tables)
- Automatically determines page sections from URL structure
- Creates intelligent previews highlighting query terms

### Rate Limiting & Ethics
- Includes appropriate delays between requests
- Uses proper User-Agent headers
- Respects the target website's resources
- Implements error handling and retry logic

## Error Handling

The server includes comprehensive error handling for:
- Network connectivity issues
- Invalid URLs or missing pages
- Malformed HTML content
- Rate limiting responses
- Cache corruption

## Limitations

- Limited to the specified EnergyPlus documentation domain
- Cache duration of 24 hours (configurable)
- Maximum of 500 pages can be discovered in one operation
- Search limited to text content (no image or PDF search)

## Extending the Server

To modify the server for other documentation sites:

1. **Change Base URL**: Update `self.base_url` in the `EnergyPlusDocsSearcher` class
2. **Modify URL Validation**: Update `_is_valid_url()` method for your target domain
3. **Adjust Content Extraction**: Modify `fetch_page_content()` for site-specific HTML structure
4. **Update Section Detection**: Customize `_extract_section()` for your site's organization

## Security Considerations

- Server only accesses the specified domain
- No external API keys or credentials required
- All data processing happens locally
- No persistent storage of cached content beyond session

## Troubleshooting

### Common Issues

1. **Connection Errors**: Check internet connectivity and target site availability
2. **Slow Performance**: Reduce `max_pages` parameter or increase cache duration
3. **Empty Results**: Try broader search terms or check if target pages exist
4. **Memory Usage**: Clear cache periodically for long-running servers

### Debug Mode
Enable debug logging by setting the logging level:
```python
logging.basicConfig(level=logging.DEBUG)
```

## Contributing

To contribute improvements:
1. Follow the existing code structure and error handling patterns
2. Add appropriate logging for new features
3. Include input validation and error handling
4. Test with various search queries and edge cases
5. Update documentation for new features

## License

This MCP server is designed to respectfully access public documentation while providing enhanced search capabilities for developers working with EnergyPlus.