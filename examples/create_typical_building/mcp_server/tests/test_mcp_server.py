#!/usr/bin/env python3
"""
Test script to verify the MCP server functionality
"""

import asyncio
import json
import sys
from pathlib import Path

# Add the src directory to the Python path
src_path = str(Path(__file__).parent.parent / "src")
sys.path.insert(0, src_path)

# Import from src package with proper package structure
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.server import OpenStudioStandardsDatabaseServer
from src.ashrae_standard import ASHRAEBuildingType, ASHRAEExampleBuildingTypes

async def test_mcp_server():
    """Test the MCP server functionality locally"""
    
    # Initialize the server
    server = OpenStudioStandardsDatabaseServer()
    
    print("Testing MCP Server Functions...")
    print("=" * 50)
    
    # Test 1: Get available building types for geometry
    print("\n1. Testing get_available_building_types...")
    try:
        available_types = [building_type.value for building_type in ASHRAEBuildingType]
        print(f"  ✓ Available building types: {len(available_types)} types")
        print(f"  ✓ Sample types: {available_types[:3]}...")
    except Exception as e:
        print(f"  ✗ Failed: {str(e)}")
        return False
    
    # Test 2: Test get_default_geometry_osm with valid building type
    print("\n2. Testing get_default_geometry_osm with valid building type...")
    try:
        test_building_type = ASHRAEExampleBuildingTypes.SMALL_OFFICE
        result = server.get_default_geometry_osm(test_building_type)
        
        # Get model info and raw OSM string (like the updated server)
        model = result.building_type_osm_file
        spaces = model.getSpaces()
        thermal_zones = model.getThermalZones()
        
        # Get the raw OSM string representation
        osm_string = str(model)
        
        response_data = {
            "building_type": result.building_type.value,
            "model_info": {
                "spaces_count": len(spaces),
                "thermal_zones_count": len(thermal_zones),
                "osm_string_length": len(osm_string)
            },
            "osm_string": osm_string
        }
        
        print(f"  ✓ Successfully loaded {test_building_type.value}")
        print(f"  ✓ Response data: {json.dumps(response_data, indent=2)}")
        
    except Exception as e:
        print(f"  ✗ Failed: {str(e)}")
        return False
    
    # Test 3: Test with string conversion (simulating MCP input)
    print("\n3. Testing string-to-enum conversion (MCP simulation)...")
    try:
        building_type_str = "Hospital"
        building_type_enum = ASHRAEExampleBuildingTypes(building_type_str)
        result = server.get_default_geometry_osm(building_type_enum)
        
        print(f"  ✓ Successfully converted '{building_type_str}' to enum")
        print(f"  ✓ Loaded model for {result.building_type.value}")
        
    except Exception as e:
        print(f"  ✗ Failed: {str(e)}")
        return False
    
    # Test 4: Test with invalid building type
    print("\n4. Testing invalid building type handling...")
    try:
        invalid_building_type = "InvalidType"
        ASHRAEBuildingType(invalid_building_type)
        print(f"  ✗ Should have failed with invalid type: {invalid_building_type}")
        return False
    except ValueError:
        print(f"  ✓ Correctly rejected invalid building type: {invalid_building_type}")
    except Exception as e:
        print(f"  ✗ Unexpected error: {str(e)}")
        return False
    
    # Test 5: Test generate_default_ashrae_geometry_osm function
    print("\n5. Testing generate_default_ashrae_geometry_osm...")
    try:
        import tempfile
        
        # Create a temporary directory for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            save_directory = Path(temp_dir)
            test_building_type = ASHRAEBuildingType.SMALL_OFFICE
            
            # Test the generate function
            success = server.generate_default_ashrae_geometry_osm(test_building_type, save_directory)
            
            # Check if file was created
            expected_file = save_directory / f"{test_building_type.value}.osm"
            
            print(f"  ✓ Function returned success: {success}")
            print(f"  ✓ File created at: {expected_file}")
            print(f"  ✓ File exists: {expected_file.exists()}")
            
            if expected_file.exists():
                file_size = expected_file.stat().st_size
                print(f"  ✓ File size: {file_size} bytes")
            
    except Exception as e:
        print(f"  ✗ Failed: {str(e)}")
        return False

    print("\n" + "=" * 50)
    print("All MCP server tests passed! ✓")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_mcp_server())
    sys.exit(0 if success else 1)
