"""
Test file for OpenStudio Model Wrapper construction creation functionality.

This test file         print(f"📊 Model summary:")
        print(f"   Total constructions: {len(model.getConstructions())}")
        print(f        print(f"📊 Material creation summary:")
        print(f"   Created: {len(created_materials)}/{len(test_materials)} materials")
        print(f"   StandardOpaque: {len(model.getStandardOpaqueMaterials())}")
        print(f"   MasslessOpaque: {len(model.getMasslessOpaqueMaterials())}")
        print(f"   AirGap: {len(model.getAirGaps())}")
        print(f"   SimpleGlazing: {len(model.getSimpleGlazings())}")
        print(f"   Gas: {len(model.getGass())}")tal materials: {len(model.getStandardOpaqueMaterials()) + len(model.getMasslessOpaqueMaterials()) + len(model.getAirGaps()) + len(model.getSimpleGlazings()) + len(model.getGass())}")idates the construction creation features implemented in
openstudio_model_wrapper.py, including JSON data loading, material creation,
and construction assembly.
"""

import sys
from pathlib import Path

# Add the src directory to Python path
src_path = str(Path(__file__).parent.parent / "src")
sys.path.insert(0, src_path)

# Import from src package with proper package structure
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import openstudio
    OPENSTUDIO_AVAILABLE = True
    print("✅ OpenStudio bindings are available")
except ImportError:
    OPENSTUDIO_AVAILABLE = False
    print("❌ OpenStudio bindings not available")

from src.openstudio_model_wrapper import OpenStudioModelWrapper


def test_construction_creation():
    """Test the construction creation functionality."""
    print("=" * 70)
    print("Testing Construction Creation")
    print("=" * 70)
    
    if not OPENSTUDIO_AVAILABLE:
        print("❌ OpenStudio not available, skipping construction creation tests")
        return
    
    try:
        # Create a simple model
        model = openstudio.model.Model()
        model_wrapper = OpenStudioModelWrapper(model)
        
        print(f"✅ Created OpenStudio model and wrapper")
        
        # Test JSON data loading
        constructions_data = model_wrapper._load_constructions_data()
        materials_data = model_wrapper._load_materials_data()
        
        print(f"✅ Loaded JSON data:")
        print(f"   Constructions: {len(constructions_data.get('constructions', []))}")
        print(f"   Materials: {len(materials_data.get('materials', []))}")
        
        # Test finding a specific construction
        test_construction_name = "Metal framed wallsW1_R8.60"
        construction_data = model_wrapper.find_construction_data(test_construction_name)
        
        if construction_data:
            print(f"✅ Found construction data for: {test_construction_name}")
            materials = construction_data.get('materials', [])
            print(f"   Materials ({len(materials)}): {', '.join(materials[:3])}{'...' if len(materials) > 3 else ''}")
        else:
            print(f"❌ Construction data not found for: {test_construction_name}")
            return
        
        # Test creating a construction
        print(f"\n🔨 Creating construction: {test_construction_name}")
        construction = model_wrapper.create_construction(test_construction_name)
        
        if construction:
            print(f"✅ Successfully created construction")
            print(f"   Name: {construction.name().get()}")
            print(f"   Layers: {construction.numLayers()}")
            
            # List the layers
            for i in range(construction.numLayers()):
                layer = construction.getLayer(i)
                layer_name = layer.name().get() if layer else "Unknown"
                print(f"   Layer {i+1}: {layer_name}")
        else:
            print(f"❌ Failed to create construction")
        
        # Test creating multiple constructions
        test_constructions = [
            "Metal framed wallsW2_R11.13",
            "ASHRAE 189.1-2009 ExtWindow ClimateZone 4-5"
        ]
        
        print(f"\n🔨 Creating multiple constructions...")
        created_constructions = []
        
        for construction_name in test_constructions:
            try:
                construction = model_wrapper.create_construction(construction_name)
                if construction:
                    created_constructions.append(construction)
                    print(f"   ✅ {construction_name} ({construction.numLayers()} layers)")
                else:
                    print(f"   ❌ {construction_name} (failed)")
            except Exception as e:
                print(f"   ❌ {construction_name} (error: {e})")
        
        print(f"\n📊 Model summary:")
        print(f"   Total constructions: {len(model.getConstructions())}")
        print(f"   Total materials: {len(model.getStandardOpaqueMaterials()) + len(model.getMasslessOpaqueMaterials()) + len(model.getAirGaps()) + len(model.getSimpleGlazings())}")
        
        # Save the model
        model_path = Path(__file__).parent / "test_constructions_model.osm"
        model.save(openstudio.toPath(str(model_path)), True)
        print(f"💾 Saved test model to: {model_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during construction creation test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_data_loading():
    """Test JSON data loading functionality."""
    print("\n" + "=" * 70)
    print("Testing JSON Data Loading")
    print("=" * 70)
    
    if not OPENSTUDIO_AVAILABLE:
        print("❌ OpenStudio not available, skipping data loading tests")
        return
    
    try:
        # Create a simple model and wrapper
        model = openstudio.model.Model()
        model_wrapper = OpenStudioModelWrapper(model)
        
        # Test data directory path
        data_dir = model_wrapper._data_dir
        print(f"📁 Data directory: {data_dir}")
        print(f"   Exists: {data_dir.exists()}")
        
        if data_dir.exists():
            constructions_file = data_dir / "ashrae_90_1.constructions.json"
            materials_file = data_dir / "ashrae_90_1.materials.json"
            
            print(f"   Constructions file: {constructions_file.exists()}")
            print(f"   Materials file: {materials_file.exists()}")
        
        # Test loading constructions data
        print(f"\n🔍 Testing constructions data loading...")
        constructions_data = model_wrapper._load_constructions_data()
        constructions_list = constructions_data.get('constructions', [])
        
        print(f"   Loaded {len(constructions_list)} constructions")
        if constructions_list:
            sample_construction = constructions_list[0]
            print(f"   Sample construction: {sample_construction.get('name', 'Unknown')}")
            print(f"   Sample materials: {sample_construction.get('materials', [])[:3]}")
        
        # Test loading materials data
        print(f"\n🔍 Testing materials data loading...")
        materials_data = model_wrapper._load_materials_data()
        materials_list = materials_data.get('materials', [])
        
        print(f"   Loaded {len(materials_list)} materials")
        if materials_list:
            sample_material = materials_list[0]
            print(f"   Sample material: {sample_material.get('name', 'Unknown')}")
            print(f"   Sample type: {sample_material.get('material_type', 'Unknown')}")
        
        # Test finding specific items
        print(f"\n🔍 Testing data lookup...")
        test_material = "1/2 in. Gypsum Board"
        material_data = model_wrapper.find_material_data(test_material)
        
        if material_data:
            print(f"   ✅ Found material: {test_material}")
            print(f"   Type: {material_data.get('material_type', 'Unknown')}")
        else:
            print(f"   ❌ Material not found: {test_material}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during data loading test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_material_creation():
    """Test individual material creation functionality."""
    print("\n" + "=" * 70)
    print("Testing Material Creation")
    print("=" * 70)
    
    if not OPENSTUDIO_AVAILABLE:
        print("❌ OpenStudio not available, skipping material creation tests")
        return
    
    try:
        # Create a simple model and wrapper
        model = openstudio.model.Model()
        model_wrapper = OpenStudioModelWrapper(model)
        
        # Test creating different types of materials
        test_materials = [
            "1/2 in. Gypsum Board",
            "1 Coat Stucco",
            "1IN Stucco",
            "25mm Stucco"
        ]
        
        print(f"🔨 Creating test materials...")
        created_materials = []
        
        for material_name in test_materials:
            try:
                material = model_wrapper._create_material_from_data(material_name)
                if material:
                    created_materials.append(material)
                    material_type = type(material).__name__
                    print(f"   ✅ {material_name} ({material_type})")
                else:
                    print(f"   ❌ {material_name} (creation failed)")
            except Exception as e:
                print(f"   ❌ {material_name} (error: {e})")
        
        print(f"\n📊 Material creation summary:")
        print(f"   Created: {len(created_materials)}/{len(test_materials)} materials")
        print(f"   StandardOpaque: {len(model.getStandardOpaqueMaterials())}")
        print(f"   MasslessOpaque: {len(model.getMasslessOpaqueMaterials())}")
        print(f"   AirGap: {len(model.getAirGaps())}")
        print(f"   SimpleGlazing: {len(model.getSimpleGlazings())}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during material creation test: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("🚀 Starting OpenStudio Model Wrapper Tests")
    print("=" * 70)
    
    results = []
    
    # Run individual tests
    results.append(("Data Loading", test_data_loading()))
    results.append(("Material Creation", test_material_creation()))
    results.append(("Construction Creation", test_construction_creation()))
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:<25} {status}")
        if result:
            passed += 1
    
    print("-" * 70)
    print(f"Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
