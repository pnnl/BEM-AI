"""
ASHRAE 90.1 Standards with OpenStudio Integration

This module extends the core ASHRAE901Standards class to work with OpenStudio Python bindings,
enabling actual creation of construction sets in OpenStudio models with ASHRAE 90.1 standards data.
"""

import logging
from typing import Dict, Optional, Any
from pathlib import Path

import openstudio

# Import our core ASHRAE standards implementation
from .ashrae_standards import ASHRAE901Standards
from . import ASHRAEBuildingType, ASHRAEClimateZone, ASHRAESpaceType

# Import OpenStudio model wrapper
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from openstudio_model_wrapper import OpenStudioModelWrapper

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



class ASHRAE901StandardsWithOpenStudio(ASHRAE901Standards):
    """
    Extended ASHRAE 90.1 Standards class that can create actual OpenStudio objects.
    
    This class combines the data lookup functionality from the core ASHRAE standards
    implementation with OpenStudio Python bindings to create real model objects.
    """
    
    def __init__(self, template: str, data_dir: Optional[str] = None):
        """
        Initialize with OpenStudio integration capability.
        
        Args:
            template: ASHRAE template string
            data_dir: Optional directory containing JSON data files (currently unused)
        """
        super().__init__(template)
    
    
    def model_add_construction_set(self, model: 'openstudio.Model', climate_zone: ASHRAEClimateZone, 
                                 building_type: ASHRAEBuildingType, # space_type: ASHRAESpaceType, 
                                 is_residential: bool = False) -> Optional[bool]:
        """
        Add an ASHRAE 90.1 construction set to an OpenStudio model.
        
        This method creates a complete construction set based on ASHRAE 90.1 standards data
        and applies it to the OpenStudio model. The construction set includes all surface
        and subsurface constructions for the specified building characteristics.
        
        Process:
        1. Find climate zone set mapping from input climate zone
        2. Lookup construction set data from ASHRAE standards database
        3. Create OpenStudio DefaultConstructionSet object with appropriate name
        4. Apply exterior surface constructions (walls, roofs, floors)
        5. Apply interior surface constructions (walls, floors, ceilings)
        6. Apply ground contact constructions (slabs, basement walls)
        7. Apply exterior subsurface constructions (windows, doors, skylights)
        8. Apply interior subsurface constructions (interior doors)
        9. Apply other constructions (partitions, shading elements)
        10. Set the construction set as the model's default
        
        The climate zone set is properly passed through the entire call chain to ensure
        consistent thermal property lookups for all construction types.
        
        Args:
            model: OpenStudio Model object to add the construction set to
            climate_zone: ASHRAE climate zone (e.g., CZ4A, CZ3B)
            building_type: Building type category (e.g., OFFICE, RETAIL, HOSPITAL)
            space_type: Specific space type within building (e.g., OPEN_OFFICE, ATTIC)
            is_residential: Whether the building is residential (affects construction requirements)
        
        Returns:
            True if construction set was successfully created and applied, None if failed
            
        Raises:
            Warning logs if climate zone set or construction data cannot be found
        """
        
        # Create model wrapper for easier operations
        model_wrapper = OpenStudioModelWrapper(model)
        
        # TODO - currently set to None. Could be Attic or Plenum at some point
        space_type = None

        logger.info(f"Adding construction set: {self.template}-{climate_zone.value}-{building_type.value}-{space_type}-is_residential{is_residential}")
        
        # Step 1: Find climate zone set
        climate_zone_set = self.find_climate_zone_set(climate_zone)
        if not climate_zone_set:
            logger.warning(f"Climate zone set not found for: {climate_zone.value}")
            return None
        
        # Step 2: Get construction set data
        construction_data = self.find_construction_set(building_type, space_type, is_residential)
        if not construction_data:
            logger.warning(f"Construction set data not found for: template={self.template}, "
                         f"building_type={building_type.value}, "
                         f"space_type={space_type}, is_residential={is_residential}")
            return None
        
        # Step 3: Create construction set name
        construction_set_name = self._make_construction_set_name(climate_zone, building_type, space_type)
        
        # Step 4: Create OpenStudio construction set
        construction_set = model_wrapper.create_construction_set(construction_set_name)
        
        # Step 5: Create and assign surface constructions
        self._apply_exterior_surface_constructions(model_wrapper, construction_set, construction_data, climate_zone_set)
        self._apply_interior_surface_constructions(model_wrapper, construction_set, construction_data)
        self._apply_ground_contact_constructions(model_wrapper, construction_set, construction_data, climate_zone_set)
        self._apply_exterior_subsurface_constructions(model_wrapper, construction_set, construction_data, climate_zone_set)
        self._apply_interior_subsurface_constructions(model_wrapper, construction_set, construction_data)
        self._apply_other_constructions(model_wrapper, construction_set, construction_data)
        
        logger.info(f"Successfully created construction set: {construction_set_name}")

        building = model.getBuilding()
        building.setDefaultConstructionSet(construction_set)
        
        return True
    
    def _make_construction_set_name(self, climate_zone: ASHRAEClimateZone, building_type: ASHRAEBuildingType, space_type: Optional[ASHRAESpaceType]) -> str:
        """Create a name for the construction set."""
        
        space_type = space_type.value if space_type is not None else 'None'

        return f"{self.template} {climate_zone.value} {building_type.value} {space_type}"
    
    def _apply_exterior_surface_constructions(self, model_wrapper: OpenStudioModelWrapper, 
                                            construction_set: 'openstudio.model.DefaultConstructionSet',
                                            data: Dict[str, Any], climate_zone_set: str):
        """Apply exterior surface constructions based on standards data."""
        exterior_surfaces = model_wrapper.create_surface_constructions()
        construction_set.setDefaultExteriorSurfaceConstructions(exterior_surfaces)
        
        # Handle special case for Attic space type
        space_type = data.get('space_type', '')
        if space_type == 'Attic':
            # Special condition: insulation on floor, uninsulated soffit
            attic_soffit = model_wrapper.create_construction('Typical Attic Soffit')
            exterior_surfaces.setFloorConstruction(attic_soffit)
        else:
            # Regular exterior floor construction
            if data.get('exterior_floor_standards_construction_type') and data.get('exterior_floor_building_category'):
                floor_construction = self._find_and_add_construction(
                    model_wrapper, 
                    'ExteriorFloor',
                    data['exterior_floor_standards_construction_type'],
                    data['exterior_floor_building_category'],
                    climate_zone_set
                )
                if floor_construction:
                    exterior_surfaces.setFloorConstruction(floor_construction)
        
        # Exterior wall construction
        if data.get('exterior_wall_standards_construction_type') and data.get('exterior_wall_building_category'):
            wall_construction = self._find_and_add_construction(
                model_wrapper,
                'ExteriorWall',
                data['exterior_wall_standards_construction_type'],
                data['exterior_wall_building_category'],
                climate_zone_set
            )
            if wall_construction:
                exterior_surfaces.setWallConstruction(wall_construction)
        
        # Exterior roof construction
        if data.get('exterior_roof_standards_construction_type') and data.get('exterior_roof_building_category'):
            roof_construction = self._find_and_add_construction(
                model_wrapper,
                'ExteriorRoof',
                data['exterior_roof_standards_construction_type'],
                data['exterior_roof_building_category'],
                climate_zone_set
            )
            if roof_construction:
                exterior_surfaces.setRoofCeilingConstruction(roof_construction)
    
    def _apply_interior_surface_constructions(self, model_wrapper: OpenStudioModelWrapper,
                                            construction_set: 'openstudio.model.DefaultConstructionSet',
                                            data: Dict[str, Any]):
        """Apply interior surface constructions."""
        interior_surfaces = model_wrapper.create_surface_constructions()
        construction_set.setDefaultInteriorSurfaceConstructions(interior_surfaces)
        
        # Interior floors
        if data.get('interior_floors'):
            interior_floor = model_wrapper.create_construction(data['interior_floors'])
            interior_surfaces.setFloorConstruction(interior_floor)
        
        # Interior walls
        if data.get('interior_walls'):
            interior_wall = model_wrapper.create_construction(data['interior_walls'])
            interior_surfaces.setWallConstruction(interior_wall)
        
        # Interior ceilings
        if data.get('interior_ceilings'):
            interior_ceiling = model_wrapper.create_construction(data['interior_ceilings'])
            interior_surfaces.setRoofCeilingConstruction(interior_ceiling)
    
    def _apply_ground_contact_constructions(self, model_wrapper: OpenStudioModelWrapper,
                                          construction_set: 'openstudio.model.DefaultConstructionSet',
                                          data: Dict[str, Any], climate_zone_set: str):
        """Apply ground contact surface constructions."""
        ground_surfaces = model_wrapper.create_surface_constructions()
        construction_set.setDefaultGroundContactSurfaceConstructions(ground_surfaces)
        
        # Ground contact floor
        if data.get('ground_contact_floor_standards_construction_type') and data.get('ground_contact_floor_building_category'):
            ground_floor = self._find_and_add_construction(
                model_wrapper,
                'GroundContactFloor',
                data['ground_contact_floor_standards_construction_type'],
                data['ground_contact_floor_building_category'],
                climate_zone_set
            )
            if ground_floor:
                ground_surfaces.setFloorConstruction(ground_floor)
        
        # Ground contact wall
        if data.get('ground_contact_wall_standards_construction_type') and data.get('ground_contact_wall_building_category'):
            ground_wall = self._find_and_add_construction(
                model_wrapper,
                'GroundContactWall',
                data['ground_contact_wall_standards_construction_type'],
                data['ground_contact_wall_building_category'],
                climate_zone_set
            )
            if ground_wall:
                ground_surfaces.setWallConstruction(ground_wall)
    
    def _apply_exterior_subsurface_constructions(self, model_wrapper: OpenStudioModelWrapper,
                                               construction_set: 'openstudio.model.DefaultConstructionSet',
                                               data: Dict[str, Any], climate_zone_set: str):
        """Apply exterior subsurface (windows, doors) constructions."""
        exterior_subsurfaces = model_wrapper.create_subsurface_constructions()
        construction_set.setDefaultExteriorSubSurfaceConstructions(exterior_subsurfaces)
        
        # Fixed windows
        if data.get('exterior_fixed_window_standards_construction_type') and data.get('exterior_fixed_window_building_category'):
            fixed_window = self._find_and_add_construction(
                model_wrapper,
                'ExteriorWindow',
                data['exterior_fixed_window_standards_construction_type'],
                data['exterior_fixed_window_building_category'],
                climate_zone_set
            )
            if fixed_window:
                exterior_subsurfaces.setFixedWindowConstruction(fixed_window)
        
        # Operable windows
        if data.get('exterior_operable_window_standards_construction_type') and data.get('exterior_operable_window_building_category'):
            operable_window = self._find_and_add_construction(
                model_wrapper,
                'ExteriorWindow',
                data['exterior_operable_window_standards_construction_type'],
                data['exterior_operable_window_building_category'],
                climate_zone_set
            )
            if operable_window:
                exterior_subsurfaces.setOperableWindowConstruction(operable_window)
        
        # Doors
        if data.get('exterior_door_standards_construction_type') and data.get('exterior_door_building_category'):
            door = self._find_and_add_construction(
                model_wrapper,
                'ExteriorDoor',
                data['exterior_door_standards_construction_type'],
                data['exterior_door_building_category'],
                climate_zone_set
            )
            if door:
                exterior_subsurfaces.setDoorConstruction(door)
        
        # Skylights
        if data.get('exterior_skylight_standards_construction_type') and data.get('exterior_skylight_building_category'):
            skylight = self._find_and_add_construction(
                model_wrapper,
                'Skylight',
                data['exterior_skylight_standards_construction_type'],
                data['exterior_skylight_building_category'],
                climate_zone_set
            )
            if skylight:
                exterior_subsurfaces.setSkylightConstruction(skylight)
    
    def _apply_interior_subsurface_constructions(self, model_wrapper: OpenStudioModelWrapper,
                                               construction_set: 'openstudio.model.DefaultConstructionSet',
                                               data: Dict[str, Any]):
        """Apply interior subsurface constructions."""
        interior_subsurfaces = model_wrapper.create_subsurface_constructions()
        construction_set.setDefaultInteriorSubSurfaceConstructions(interior_subsurfaces)
        
        # Interior doors
        if data.get('interior_doors'):
            interior_door = model_wrapper.create_construction(data['interior_doors'])
            interior_subsurfaces.setDoorConstruction(interior_door)
    
    def _apply_other_constructions(self, model_wrapper: OpenStudioModelWrapper,
                                 construction_set: 'openstudio.model.DefaultConstructionSet',
                                 data: Dict[str, Any]):
        """Apply other construction types (partitions, shading, etc.)."""
        # Interior partitions
        if data.get('interior_partitions'):
            interior_partition = model_wrapper.create_construction(data['interior_partitions'])
            construction_set.setInteriorPartitionConstruction(interior_partition)
        
        # Space shading
        if data.get('space_shading'):
            space_shading = model_wrapper.create_construction(data['space_shading'])
            construction_set.setSpaceShadingConstruction(space_shading)
        
        # Building shading
        if data.get('building_shading'):
            building_shading = model_wrapper.create_construction(data['building_shading'])
            construction_set.setBuildingShadingConstruction(building_shading)
        
        # Site shading
        if data.get('site_shading'):
            site_shading = model_wrapper.create_construction(data['site_shading'])
            construction_set.setSiteShadingConstruction(site_shading)
    
    def _find_and_add_construction(self, model_wrapper: OpenStudioModelWrapper, 
                                 intended_surface_type: str, standards_construction_type: str,
                                 building_category: str, climate_zone_set: str) -> Optional['openstudio.model.Construction']:
        """
        Find and add a construction based on standards data.
        
        This implements the model_find_and_add_construction method:
        1. Find construction properties (thermal requirements)
        2. Look up the construction name from properties
        3. Create the construction
        
        
        Args:
            model_wrapper: OpenStudio model wrapper
            intended_surface_type: Type of surface (e.g., 'ExteriorWall')
            standards_construction_type: Standards construction type
            building_category: Building category
            climate_zone_set: Climate zone set string for properties lookup
            
        Returns:
            Construction object if created successfully
        """
        # Step 1: Find construction properties (thermal requirements)
        construction_props = model_wrapper.find_construction_properties(
            climate_zone_set, intended_surface_type, standards_construction_type, building_category
        )
        
        if not construction_props:
            # Fallback to placeholder if properties not found
            construction_name = f"{self.template} {intended_surface_type} {standards_construction_type} {building_category}"
            logger.warning(f"Construction properties not found, creating placeholder: {construction_name}")
            return model_wrapper.create_construction(construction_name)
        
        # Step 2: Get the actual construction name from properties
        construction_name = construction_props.get('construction')
        if not construction_name:
            logger.warning(f"No construction name in properties for: {intended_surface_type}")
            construction_name = f"{self.template} {intended_surface_type} {standards_construction_type} {building_category}"
        
        # Step 3: Check if construction already exists
        existing = model_wrapper.find_construction_by_name(construction_name)
        if existing:
            logger.debug(f"Found existing construction: {construction_name}")
            return existing
        
        # Step 4: Create the construction using our Step 2 implementation
        construction = model_wrapper.create_construction(construction_name)
        
        if construction and construction.numLayers() > 0:
            logger.info(f"Created construction from JSON data: {construction_name} ({construction.numLayers()} layers)")
        else:
            logger.debug(f"Created placeholder construction: {construction_name}")
        
        return construction

def create_sample_model_with_construction_set():
    """
    Create a sample OpenStudio model with a construction set applied.
    
    This demonstrates the complete workflow from data lookup to model creation.
    """
    
    print("🏗️ Creating sample OpenStudio model with ASHRAE 90.1 construction set...")
    
    # Create a new OpenStudio model
    model = openstudio.model.Model()
    
    # Create the standards object
    standards = ASHRAE901StandardsWithOpenStudio('90.1-2013')
    
    # Define construction set parameters
    climate_zone = ASHRAEClimateZone.CZ4A
    building_type = ASHRAEBuildingType.OFFICE
    space_type = ASHRAESpaceType.OPEN_OFFICE
    is_residential = False
    
    print(f"📋 Parameters:")
    print(f"   Template: {standards.template}")
    print(f"   Climate Zone: {climate_zone.value}")
    print(f"   Building Type: {building_type.value}")
    print(f"   Space Type: {space_type.value}")
    print(f"   Residential: {is_residential}")
    
    # Create construction set using our Python implementation
    construction_set = standards.model_add_construction_set(
        model, climate_zone, building_type, is_residential
    )
    
    if construction_set:
        print(f"✅ Successfully created construction set: {construction_set.name().get()}")
        
        # Apply construction set as default for the model
        model.getBuilding().setDefaultConstructionSet(construction_set)
        print(f"📐 Applied construction set as model default")
        
        # Save the model
        model_path = Path(__file__).parent / "sample_model_with_constructions.osm"
        model.save(openstudio.toPath(str(model_path)), True)
        print(f"💾 Saved model to: {model_path}")
        
        # Print model summary
        constructions = len(model.getConstructions())
        construction_sets = len(model.getDefaultConstructionSets())
        print(f"📊 Model contains: {constructions} constructions, {construction_sets} construction sets")
        
        return model
    else:
        print("❌ Failed to create construction set")
        return None


def main():
    """Demonstrate OpenStudio integration functionality."""
    print("=" * 80)
    print("ASHRAE 90.1 Standards with OpenStudio Integration")
    print("=" * 80)
    
    print(f"\n✅ OpenStudio Python bindings available")
    print(f"📦 OpenStudio version: {openstudio.openStudioVersion()}")
    
    # Test the integrated functionality
    try:
        # Test basic functionality with sample data
        print(f"\n🧪 Testing data lookup functionality...")
        standards = ASHRAE901StandardsWithOpenStudio('90.1-2013')
        
        construction_data = standards.find_construction_set(
            ASHRAEBuildingType.OFFICE, 
            ASHRAESpaceType.OFFICE, 
            False
        )
        
        if construction_data:
            print(f"✅ Data lookup successful")
            print(f"   Found construction data for Office OpenOffice")
        
        # Create sample model
        print(f"\n🏗️ Creating sample model...")
        model = create_sample_model_with_construction_set()
        
        if model:
            print(f"\n🎉 OpenStudio integration successful!")
            print(f"✅ Successfully integrated ASHRAE standards data with OpenStudio model creation")
        
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
