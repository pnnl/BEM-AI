#!/usr/bin/env python3
"""
Simple test client for the Foundational Geometry Agent
"""
import asyncio
from automa_ai.client.simple_client import SimpleClient

async def main():
    # Initialize client pointing to the agent
    client = SimpleClient(agent_url="http://localhost:8081")
    
    print("=" * 60)
    print("Testing Foundational Geometry Agent")
    print("=" * 60)
    
    # Test 0: Ask what tools are available
    print("\n🛠️  Test 0: What tools are available?")
    print("-" * 60)
    async for chunk in client.send_streaming_message(
        "What tools do you have available?",
        context_id="test-session-1"
    ):
        # Handle status-update events with streaming text
        result = chunk.get("result", {})
        if result.get("kind") == "status-update":
            status = result.get("status", {})
            message = status.get("message", {})
            parts = message.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and part.get("kind") == "text":
                    print(part.get("text", ""), end="", flush=True)
    print("\n")
    
    # Test 1: Ask about available building types
    print("\n📋 Test 1: What building types are available?")
    print("-" * 60)
    async for chunk in client.send_streaming_message(
        "What building types are available for geometry generation?",
        context_id="test-session-1"
    ):
        # Handle status-update events with streaming text
        result = chunk.get("result", {})
        if result.get("kind") == "status-update":
            status = result.get("status", {})
            message = status.get("message", {})
            parts = message.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and part.get("kind") == "text":
                    print(part.get("text", ""), end="", flush=True)
    print("\n")
    
    # Test 2: Ask about climate zones
    print("\n🌍 Test 2: What climate zones are available?")
    print("-" * 60)
    async for chunk in client.send_streaming_message(
        "What climate zones are supported?",
        context_id="test-session-1"
    ):
        result = chunk.get("result", {})
        if result.get("kind") == "status-update":
            status = result.get("status", {})
            message = status.get("message", {})
            parts = message.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and part.get("kind") == "text":
                    print(part.get("text", ""), end="", flush=True)
    print("\n")
    
    # Test 3: Create a simple building (you might want to adjust the path)
    print("\n🏢 Test 3: Create a building model")
    print("-" * 60)
    async for chunk in client.send_streaming_message(
        "Create a small office building with ASHRAE 90.1-2013 constructions for climate zone 4A and save it to /tmp/test_models",
        context_id="test-session-1"
    ):
        result = chunk.get("result", {})
        if result.get("kind") == "status-update":
            status = result.get("status", {})
            message = status.get("message", {})
            parts = message.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and part.get("kind") == "text":
                    print(part.get("text", ""), end="", flush=True)
    print("\n")
    
    print("\n" + "=" * 60)
    print("✅ Testing complete!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
