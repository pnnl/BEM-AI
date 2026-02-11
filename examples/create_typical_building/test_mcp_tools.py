#!/usr/bin/env python3
"""
Test the OpenStudio Standards MCP server tools
"""
import asyncio
import json
from mcp.client.sse import sse_client
from mcp import ClientSession

MCP_URL = "http://localhost:8082/sse"

async def test_mcp_server():
    """Test the MCP server's available tools and resources"""
    
    print("🔌 Connecting to MCP server at", MCP_URL)
    
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the session
            await session.initialize()
            print("✅ Connected and initialized\n")
            
            # 1. List available tools
            print("=" * 60)
            print("📋 Available Tools:")
            print("=" * 60)
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"\n🔧 {tool.name}")
                print(f"   {tool.description}")
                if hasattr(tool, 'inputSchema'):
                    print(f"   Schema: {json.dumps(tool.inputSchema, indent=6)}")
            
            # 2. List available resources
            print("\n" + "=" * 60)
            print("📦 Available Resources:")
            print("=" * 60)
            resources = await session.list_resources()
            for resource in resources.resources:
                print(f"\n📄 {resource.uri}")
                print(f"   {resource.name}: {resource.description}")
            
            # 3. Test get_available_building_types tool
            print("\n" + "=" * 60)
            print("🏗️  Testing: get_available_building_types")
            print("=" * 60)
            result = await session.call_tool(
                name="get_available_building_types",
                arguments={}
            )
            print(json.dumps(json.loads(result.content[0].text), indent=2))
            
            # 4. Test get_ashrae_enumeration_values tool
            print("\n" + "=" * 60)
            print("📊 Testing: get_ashrae_enumeration_values")
            print("=" * 60)
            result = await session.call_tool(
                name="get_ashrae_enumeration_values",
                arguments={}
            )
            data = json.loads(result.content[0].text)
            print(f"Templates: {data.get('templates', [])[:3]}... ({len(data.get('templates', []))} total)")
            print(f"Climate Zones: {data.get('climate_zones', [])[:3]}... ({len(data.get('climate_zones', []))} total)")
            print(f"Building Types: {data.get('building_types', [])[:5]}... ({len(data.get('building_types', []))} total)")
            
            # 5. Test generate_default_ashrae_geometry_osm tool
            print("\n" + "=" * 60)
            print("🏢 Testing: generate_default_ashrae_geometry_osm")
            print("=" * 60)
            result = await session.call_tool(
                name="generate_default_ashrae_geometry_osm",
                arguments={
                    "building_type": "SmallOffice",
                    "save_directory": "/tmp/mcp_test"
                }
            )
            response = json.loads(result.content[0].text)
            print(json.dumps(response, indent=2))
            
            print("\n" + "=" * 60)
            print("✅ All tests completed!")
            print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_mcp_server())
