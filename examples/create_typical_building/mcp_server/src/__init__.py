from .server import serve


def main():
    """Main entry point for the OpenStudio Standards MCP server"""
    import argparse
    
    parser = argparse.ArgumentParser(description="OpenStudio Standards MCP Server")
    parser.add_argument("--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--port", type=int, default=8082, help="Port to bind to (default: 8082)")
    parser.add_argument("--transport", default="sse", choices=["sse"], help="Transport type (default: sse)")
    
    args = parser.parse_args()
    
    # FastMCP's run() is synchronous, no need for asyncio
    serve(host=args.host, port=args.port, transport=args.transport)


if __name__ == "__main__":
    main()
