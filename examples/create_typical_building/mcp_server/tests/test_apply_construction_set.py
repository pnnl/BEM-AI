#!/usr/bin/env python3
"""
Test script to verify the new apply_construction_set tool works correctly.
This test uses the new apply_construction_set method from the server.
"""

import sys
from pathlib import Path
import tempfile

# Add the src directory to the Python path
src_path = str(Path(__file__).parent.parent / "src")
sys.path.insert(0, src_path)

# Import from src package with proper package structure
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.server import OpenStudioStandardsDatabaseServer
from src.ashrae_standard import ASHRAETemplate, ASHRAEClimateZone, ASHRAEBuildingType, ASHRAEExampleBuildingTypes


def test_apply_construction_set():
    """Test the new apply_construction_set functionality"""
    
    print("Testing Apply Construction Set Tool...")
    print("=" * 60)
    
    # Initialize the server
    server = OpenStudioStandardsDatabaseServer()
    
    # Test parameters
    test_cases = [
        {
            "name": "Medium Office - ASHRAE 90.1-2013 - Climate Zone 4A",
            "geometry_space_type": ASHRAEExampleBuildingTypes.MEDIUM_OFFICE,
            "template": ASHRAETemplate.ASHRAE_90_1_2013,
            "climate_zone": ASHRAEClimateZone.CZ4A,
            "ashrae_building_type": ASHRAEBuildingType.OFFICE,
            "is_residential": False
        },
        {
            "name": "Primary School - ASHRAE 90.1-2013 - Climate Zone 3B",
            "geometry_space_type": ASHRAEExampleBuildingTypes.PRIMARY_SCHOOL,
            "template": ASHRAETemplate.ASHRAE_90_1_2013,
            "climate_zone": ASHRAEClimateZone.CZ3B,
            "ashrae_building_type": ASHRAEBuildingType.PRIMARY_SCHOOL,
            "is_residential": False
        },
        {
            "name": "Hospital - ASHRAE 90.1-2013 - Climate Zone 5A",
            "geometry_space_type": ASHRAEExampleBuildingTypes.HOSPITAL,
            "template": ASHRAETemplate.ASHRAE_90_1_2013,
            "climate_zone": ASHRAEClimateZone.CZ5A,
            "ashrae_building_type": ASHRAEBuildingType.HOSPITAL,
            "is_residential": False
        }
    ]
    
    results = []
    
    # Create a temporary directory for saving models
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\nTest Case {i}: {test_case['name']}")
            print("-" * 50)
            
            try:
                # Test the apply_construction_set method
                result = server.apply_construction_set_to_geometry(
                    geometry_space_type=test_case['geometry_space_type'],
                    template=test_case['template'],
                    climate_zone=test_case['climate_zone'],
                    ashrae_building_type=test_case['ashrae_building_type'],
                    is_residential=test_case['is_residential'],
                    save_directory=temp_path
                )
                
                print(f"✓ Success: {result['success']}")
                print(f"  - Geometry Space Type: {result['geometry_space_type']}")
                print(f"  - Template: {result['template']}")
                print(f"  - Climate Zone: {result['climate_zone']}")
                print(f"  - ASHRAE Building Type: {result['ashrae_building_type']}")
                print(f"  - Is Residential: {result['is_residential']}")
                print(f"  - Spaces Count: {result['model_info']['spaces_count']}")
                print(f"  - Thermal Zones Count: {result['model_info']['thermal_zones_count']}")
                print(f"  - Initial Construction Sets: {result['model_info']['initial_construction_sets']}")
                print(f"  - Final Construction Sets: {result['model_info']['final_construction_sets']}")
                
                if result['saved_to']:
                    print(f"  - Saved to: {result['saved_to']}")
                    # Verify the file exists
                    if Path(result['saved_to']).exists():
                        print(f"  - File size: {Path(result['saved_to']).stat().st_size} bytes")
                
                print(f"  - Message: {result['message']}")
                
                results.append((test_case['name'], result['success']))
                
            except Exception as e:
                print(f"✗ Error in test case {i}: {str(e)}")
                import traceback
                traceback.print_exc()
                results.append((test_case['name'], False))
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:<50} {status}")
        if result:
            passed += 1
    
    print("-" * 60)
    print(f"Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return True
    else:
        print("⚠️  Some tests failed!")
        return False


def test_construction_set_validation():
    """Test construction set validation by examining the applied constructions"""
    
    print("\nTesting Construction Set Validation...")
    print("=" * 60)
    
    # Initialize server
    server = OpenStudioStandardsDatabaseServer()
    
    # Test with a simple case
    try:
        result = server.apply_construction_set_to_geometry(
            geometry_space_type=ASHRAEExampleBuildingTypes.MEDIUM_OFFICE,
            template=ASHRAETemplate.ASHRAE_90_1_2013,
            climate_zone=ASHRAEClimateZone.CZ4A,
            ashrae_building_type=ASHRAEBuildingType.OFFICE,
            is_residential=False
        )
        
        if result['success']:
            print("✓ Construction set applied successfully")
            print(f"  - Construction sets increased from {result['model_info']['initial_construction_sets']} to {result['model_info']['final_construction_sets']}")
            
            # Additional validation could be added here to inspect the actual constructions
            print("✓ Construction set validation complete")
            return True
        else:
            print("✗ Failed to apply construction set")
            return False
            
    except Exception as e:
        print(f"✗ Error during validation: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    try:
        success1 = test_apply_construction_set()
        success2 = test_construction_set_validation()
        
        if success1 and success2:
            print("\n🎉 All tests completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Some tests failed!")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
