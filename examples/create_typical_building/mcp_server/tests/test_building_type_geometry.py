#!/usr/bin/env python3
"""
Simple test to verify building type geometry loading works
"""
import sys
from pathlib import Path

# Add the src directory to the Python path
src_path = str(Path(__file__).parent.parent / "src")
sys.path.insert(0, src_path)

# Import from src package with proper package structure
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.server import OpenStudioStandardsDatabaseServer
from src.ashrae_standard import ASHRAEExampleBuildingTypes

def test_building_type_geometry():
    """Test that building type geometry loading works"""
    
    print("Testing Building Type Geometry Loading...")
    print("=" * 50)
    
    # Initialize the server
    server = OpenStudioStandardsDatabaseServer()
    
    # Test with a few building types that should have geometry files
    test_building_types = [
        ASHRAEExampleBuildingTypes.SMALL_OFFICE,
        ASHRAEExampleBuildingTypes.MEDIUM_OFFICE,
        ASHRAEExampleBuildingTypes.HOSPITAL,
        ASHRAEExampleBuildingTypes.PRIMARY_SCHOOL
    ]
    
    for building_type in test_building_types:
        print(f"\nTesting {building_type.value}...")
        try:
            result = server.get_default_geometry_osm(building_type)
            model = result.building_type_osm_file
            spaces = model.getSpaces()
            thermal_zones = model.getThermalZones()
            
            print(f"  ✓ Successfully loaded {building_type.value}")
            print(f"  ✓ Spaces: {len(spaces)}")
            print(f"  ✓ Thermal zones: {len(thermal_zones)}")
            print(f"  ✓ Building type in result: {result.building_type.value}")
            
        except Exception as e:
            print(f"  ✗ Failed to load {building_type.value}: {str(e)}")
            return False
    
    print("\n" + "=" * 50)
    print("Building type geometry loading tests passed! ✓")
    return True

if __name__ == "__main__":
    success = test_building_type_geometry()
    sys.exit(0 if success else 1)
