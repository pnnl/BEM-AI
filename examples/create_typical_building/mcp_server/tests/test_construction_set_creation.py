#!/usr/bin/env python3
"""
Test script to verify the model_add_construction_set function works correctly.
This test uses get_default_geometry_osm to generate test models.
"""

import sys
from pathlib import Path

# Add the src directory to the Python path
src_path = str(Path(__file__).parent.parent / "src")
sys.path.insert(0, src_path)

# Import from src package with proper package structure
sys.path.insert(0, str(Path(__file__).parent.parent))
import openstudio
from src.server import OpenStudioStandardsDatabaseServer
from src.ashrae_standard import ASHRAE901StandardsWithOpenStudio
from src.ashrae_standard import ASHRAESpaceType, ASHRAETemplate, ASHRAEClimateZone, ASHRAEBuildingType, ASHRAEExampleBuildingTypes


def test_construction_set_creation():
    """Test applying construction sets to models using get_default_geometry_osm"""
    
    print("Testing Construction Set Creation...")
    print("=" * 60)
    
    # Initialize the server and standards
    server = OpenStudioStandardsDatabaseServer()
    
    # Test parameters - using building types that have geometry files
    test_cases = [
        {
            "geometry_file": ASHRAEExampleBuildingTypes.MEDIUM_OFFICE,
            "building_type": ASHRAEBuildingType.OFFICE,
            "template": ASHRAETemplate.ASHRAE_90_1_2013,
            "climate_zone": ASHRAEClimateZone.CZ4A,
            "space_type": None,
            "is_residential": False
        },
        {
            "geometry_file": ASHRAEExampleBuildingTypes.PRIMARY_SCHOOL,
            "building_type": ASHRAEBuildingType.PRIMARY_SCHOOL, #TODO
            "template": ASHRAETemplate.ASHRAE_90_1_2013,
            "climate_zone": ASHRAEClimateZone.CZ3B,
            "space_type": None,
            "is_residential": False
        },
        {
            "geometry_file": ASHRAEExampleBuildingTypes.HOSPITAL,
            "building_type": ASHRAEBuildingType.HOSPITAL, #TODO
            "template": ASHRAETemplate.ASHRAE_90_1_2013,
            "climate_zone": ASHRAEClimateZone.CZ5A,
            "space_type": None,
            "is_residential": False
        }
    ]
    
    results = []

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case['building_type'].value}")
        print("-" * 40)

        try:
            # Step 1: Get default geometry using the server method
            print(f"Loading geometry for {test_case['building_type'].value}...")
            geometry_result = server.get_default_geometry_osm(test_case['geometry_file'])
            model = geometry_result.building_type_osm_file

            # Verify model was loaded correctly
            spaces = model.getSpaces()
            thermal_zones = model.getThermalZones()
            print(f"  - Loaded model with {len(spaces)} spaces and {len(thermal_zones)} thermal zones")

            # Get initial construction set count (should be 0 or minimal)
            initial_construction_sets = model.getDefaultConstructionSets()
            print(f"  - Initial construction sets: {len(initial_construction_sets)}")

            # Step 2: Create ASHRAE standards instance
            standards = ASHRAE901StandardsWithOpenStudio(test_case['template'].value)

            # Step 3: Apply construction set
            print(f"Applying {test_case['template'].value} construction set...")
            print(f"  - Climate Zone: {test_case['climate_zone'].value}")
            print(f"  - Building Type: {test_case['building_type'].value}")
            print(f"  - Space Type: {test_case['space_type'].value if test_case['space_type'] is not None else 'None'}")
            print(f"  - Is Residential: {test_case['is_residential']}")

            success = standards.model_add_construction_set(
                model=model,
                climate_zone=test_case['climate_zone'],
                building_type=test_case['building_type'],
                is_residential=test_case['is_residential']
            )

            # Step 4: Verify construction set was applied
            if success:
                print("  ✓ Construction set applied successfully")
                results.append((test_case['building_type'].value, True))
            else:
                print("  ✗ Failed to apply construction set")
                results.append((test_case['building_type'].value, False))

        except Exception as e:
            print(f"  ✗ Error in test case {i}: {str(e)}")
            import traceback
            traceback.print_exc()
            results.append((test_case['building_type'].value, False))

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = 0
    total = len(results)

    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:<25} {status}")
        if result:
            passed += 1

    print("-" * 60)
    print(f"Overall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed!")
    
    print("\n" + "=" * 60)
    print("Construction Set Creation Test Complete")


def test_construction_set_validation():
    """Test construction set creation with validation of specific constructions"""
    
    print("\nTesting Construction Set Validation...")
    print("=" * 60)
    
    # Initialize server and get a model
    server = OpenStudioStandardsDatabaseServer()
    geometry_result = server.get_default_geometry_osm(ASHRAEExampleBuildingTypes.MEDIUM_OFFICE)
    model = geometry_result.building_type_osm_file
    
    # Apply construction set
    standards = ASHRAE901StandardsWithOpenStudio(ASHRAETemplate.ASHRAE_90_1_2013.value)

    success = standards.model_add_construction_set(
        model=model,
        climate_zone=ASHRAEClimateZone.CZ4A,
        building_type=ASHRAEBuildingType.OFFICE,
        is_residential=False
    )
    
    if success:
        print("✓ Construction set applied successfully")
        # Get the default construction set
        default_cs_optional = model.getBuilding().defaultConstructionSet()
        if default_cs_optional.is_initialized():
            default_cs = default_cs_optional.get()
            print(f"Default Construction Set: {default_cs.nameString()}")

            # Check exterior surface constructions
            ext_surface_cs = default_cs.defaultExteriorSurfaceConstructions()
            if ext_surface_cs.is_initialized():
                ext_cs = ext_surface_cs.get()
                print("\nExterior Surface Constructions:")

                # Wall construction
                wall_construction = ext_cs.wallConstruction()
                if wall_construction.is_initialized():
                    wall = wall_construction.get()
                    print(f"  - Wall: {wall.nameString()}")
                    print(f"    Layers: {len(wall.to_Construction().get().layers())}")

                # Roof construction
                roof_construction = ext_cs.roofCeilingConstruction()
                if roof_construction.is_initialized():
                    roof = roof_construction.get()
                    print(f"  - Roof: {roof.nameString()}")
                    print(f"    Layers: {len(roof.to_Construction().get().layers())}")

                # Floor construction
                floor_construction = ext_cs.floorConstruction()
                if floor_construction.is_initialized():
                    floor = floor_construction.get()
                    print(f"  - Floor: {floor.nameString()}")
                    print(f"    Layers: {len(floor.to_Construction().get().layers())}")

            # Check exterior subsurface constructions
            ext_subsurface_cs = default_cs.defaultExteriorSubSurfaceConstructions()
            if ext_subsurface_cs.is_initialized():
                ext_sub_cs = ext_subsurface_cs.get()
                print("\nExterior SubSurface Constructions:")

                # Window construction
                window_construction = ext_sub_cs.fixedWindowConstruction()
                if window_construction.is_initialized():
                    window = window_construction.get()
                    print(f"  - Window: {window.nameString()}")

                # Door construction
                door_construction = ext_sub_cs.doorConstruction()
                if door_construction.is_initialized():
                    door = door_construction.get()
                    print(f"  - Door: {door.nameString()}")

        print("\n✓ Construction set validation complete")
        print("\n🎉 ✅ Test passed successfully!")
    else:
        print("✗ Failed to apply construction set for validation")


if __name__ == "__main__":
    try:
        test_construction_set_creation()
        test_construction_set_validation()
        print("\n🎉 All tests completed!")
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
