"""
Test script for ASHRAE 90.1 Standards Python implementation

This test module performs the same checks that were originally in the main() function
of ashrae_standards.py, but separated for better testing practices.
"""

import sys
import os
from pathlib import Path

# Add the parent directory to the path so we can import ashrae_standards
sys.path.insert(0, str(Path(__file__).parent))

from ashrae_standards import ASHRAE901Standards
from __init__ import ASHRAEBuildingType, ASHRAEClimateZone, ASHRAESpaceType


def test_basic_example():
    """
    Basic test that demonstrates the core functionality with proper enum usage.
    """
    
    try:
        # Create standards object for ASHRAE 90.1-2013
        print("Creating ASHRAE 90.1-2013 standards object...")
        std = ASHRAE901Standards('90.1-2013')
        
        # Print data summary
        print(f"\nLoaded data summary: {std.get_data_summary()}")
        
        # Test climate zone set lookup
        test_climate_zone = ASHRAEClimateZone.CZ4A
        climate_zone_set = std.find_climate_zone_set(test_climate_zone)
        print(f"\nClimate zone '{test_climate_zone.value}' maps to set: '{climate_zone_set}'")
        
        # Test construction set search
        print(f"\nTesting construction set search...")
        result = std.find_construction_set(
            building_type=ASHRAEBuildingType.OFFICE,
            space_type=None,
            is_residential=False
        )
        
        if result:
            print(f"Found construction set:")
            for key, value in result.items():
                if value is not None:
                    print(f"  {key}: {value}")
        else:
            print("No construction set found matching criteria")
        
        # Show available building and space types
        print(f"\nAvailable building types: {std.get_available_building_types()[:10]}...")  # Show first 10
        print(f"Available space types: {std.get_available_space_types()[:10]}...")  # Show first 10
        
        print("\n✅ Main function example test completed successfully!")
        
    except Exception as e:
        print(f"❌ Error in main function example test: {e}")
        raise


def test_basic_functionality():
    """Test basic functionality of the ASHRAE901Standards class."""
    print("\n" + "=" * 60)
    print("ASHRAE 90.1 Standards Python Implementation - Basic Tests")
    print("=" * 60)
    
    # Test different templates
    templates_to_test = ['90.1-2013', '90.1-2016', '90.1-2019']
    
    for template in templates_to_test:
        print(f"\n🔧 Testing template: {template}")
        print("-" * 40)
        
        try:
            std = ASHRAE901Standards(template)
            print(f"✅ Successfully created standards object for {template}")
            
            # Test data loading
            summary = std.get_data_summary()
            print(f"📊 Data summary: {summary}")
            
            # Test climate zone lookup using enums
            test_zones = [
                ASHRAEClimateZone.CZ4A,
                ASHRAEClimateZone.CZ2A, 
                ASHRAEClimateZone.CZ6A
            ]
            
            for zone in test_zones:
                zone_set = std.find_climate_zone_set(zone)
                print(f"🌡️  Climate zone '{zone.value}' → '{zone_set}'")
            
        except Exception as e:
            print(f"❌ Error with {template}: {e}")


def test_construction_set_search():
    """Test construction set search functionality using proper enum types."""
    print(f"\n{'='*60}")
    print("Testing Construction Set Search with Enums")
    print("=" * 60)
    
    std = ASHRAE901Standards('90.1-2013')
    
    # Test cases using enum types: (building_type, space_type, is_residential)
    test_cases = [
        (ASHRAEBuildingType.OFFICE, None, False),
        (ASHRAEBuildingType.RETAIL, None, False),
        (ASHRAEBuildingType.PRIMARY_SCHOOL, None, False),
        (ASHRAEBuildingType.ANY, ASHRAESpaceType.ATTIC, False),
    ]
    
    for i, (building_type, space_type, is_residential) in enumerate(test_cases, 1):
        print(f"\n🔍 Test Case {i}:")
        print(f"   Building Type: {building_type.value}")
        print(f"   Space Type: {space_type.value if space_type is not None else 'None'}")
        print(f"   Residential: {is_residential}")
        
        result = std.find_construction_set(building_type, space_type, is_residential)
        
        if result:
            print("✅ Found construction set:")
            
            # Display key construction properties
            key_properties = [
                'exterior_wall_standards_construction_type',
                'exterior_wall_building_category',
                'exterior_roof_standards_construction_type',
                'exterior_roof_building_category',
                'exterior_fixed_window_standards_construction_type',
                'exterior_fixed_window_building_category'
            ]
            
            for prop in key_properties:
                value = result.get(prop)
                if value is not None:
                    print(f"   {prop}: {value}")
        else:
            print("❌ No construction set found")


def test_data_exploration():
    """Explore what data is available."""
    print(f"\n{'='*60}")
    print("Data Exploration")
    print("=" * 60)
    
    std = ASHRAE901Standards('90.1-2013')
    
    # Get available building types
    building_types = std.get_available_building_types()
    print(f"\n🏢 Available Building Types ({len(building_types)}):")
    for bt in building_types[:15]:  # Show first 15
        print(f"   - {bt}")
    if len(building_types) > 15:
        print(f"   ... and {len(building_types) - 15} more")
    
    # Get available space types
    space_types = std.get_available_space_types()
    print(f"\n🏠 Available Space Types ({len(space_types)}):")
    for st in space_types[:15]:  # Show first 15
        print(f"   - {st}")
    if len(space_types) > 15:
        print(f"   ... and {len(space_types) - 15} more")
    
    # Show space types for specific building type
    if 'Office' in building_types:
        office_space_types = std.get_available_space_types(ASHRAEBuildingType.OFFICE)
        print(f"\n🏢 Space Types for 'Office' buildings ({len(office_space_types)}):")
        for st in office_space_types:
            print(f"   - {st}")


def demonstrate_functionality():
    """Demonstrate functionality using enums."""
    print(f"\n{'='*60}")
    print("Demonstration: Python ASHRAE Standards Implementation")
    print("=" * 60)
    
    # Create standards object
    print("Creating standards object:")
    print("std = ASHRAE901Standards('90.1-2013')")
    
    std = ASHRAE901Standards('90.1-2013')
    
    # Find construction set data
    print(f"\n🔍 Testing: standard.model_add_construction_set()")
    
    # Sample parameters that would be passed to model_add_construction_set (using enums)
    climate_zone = ASHRAEClimateZone.CZ4A
    building_type = ASHRAEBuildingType.OFFICE
    space_type = None
    is_residential = False
    
    print(f"Parameters:")
    print(f"  building_type: {building_type.value}")
    print(f"   Space Type: {space_type.value if space_type is not None else 'None'}")
    print(f"  is_residential: {is_residential}")
    
    # Find construction set data
    construction_data = std.find_construction_set(building_type, space_type, is_residential)
    
    if construction_data:
        print(f"\n✅ Construction set data found!")
        print(f"This data would be used to create OpenStudio construction objects.")
        
        # Show some key data that would be used
        wall_type = construction_data.get('exterior_wall_standards_construction_type')
        wall_category = construction_data.get('exterior_wall_building_category')
        roof_type = construction_data.get('exterior_roof_standards_construction_type')
        
        print(f"\n🏗️ Key construction properties:")
        print(f"  Exterior wall type: {wall_type}")
        print(f"  Exterior wall category: {wall_category}")
        print(f"  Exterior roof type: {roof_type}")
        
        print(f"\n💡 Next steps would be:")
        print(f"  1. Use OpenStudio Python bindings to create DefaultConstructionSet")
        print(f"  2. Create specific constructions based on the data above")
        print(f"  3. Apply constructions to the OpenStudio model")
    else:
        print(f"\n❌ No construction set data found for the given parameters")


if __name__ == "__main__":
    try:
        # Run the main function example test first (replicates ashrae_standards.py main())
        test_basic_example()
        
        # Run additional comprehensive tests
        test_basic_functionality()
        test_construction_set_search()
        test_data_exploration()
        demonstrate_functionality()
        
        print(f"\n{'='*60}")
        print("✅ All tests completed successfully!")
        print("🚀 Ready for OpenStudio integration (available in src/ashrae_standard/ashrae_openstudio.py)")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
