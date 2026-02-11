"""
OpenStudio Model Wrapper

This module provides a clean Python interface for creating construction sets and related
objects in OpenStudio models using the Python bindings.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import openstudio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OpenStudioModelWrapper:
    """
    Python wrapper for OpenStudio Model operations.
    
    This class provides a clean interface for creating construction sets and related
    objects in OpenStudio models using the Python bindings.
    """
    
    def __init__(self, model: 'openstudio.Model'):
        """
        Initialize with an OpenStudio model.
        
        Args:
            model: OpenStudio Model object
        """
        
        self.model = model

         # Cache for JSON data to avoid repeated file reads
        self._constructions_data = None
        self._materials_data = None
        self._data_dir = Path(__file__).parent.parent / "resources" / "standard_data"
    
    
    def create_construction_set(self, name: str) -> 'openstudio.model.DefaultConstructionSet':
        """
        Create a new DefaultConstructionSet in the model.
        
        Args:
            name: Name for the construction set
            
        Returns:
            OpenStudio DefaultConstructionSet object
        """
        construction_set = openstudio.model.DefaultConstructionSet(self.model)
        construction_set.setName(name)
        
        logger.debug(f"Created construction set: {name}")
        return construction_set
    
    def create_surface_constructions(self) -> 'openstudio.model.DefaultSurfaceConstructions':
        """
        Create a new DefaultSurfaceConstructions object.
        
        Returns:
            OpenStudio DefaultSurfaceConstructions object
        """
        return openstudio.model.DefaultSurfaceConstructions(self.model)
    
    def create_subsurface_constructions(self) -> 'openstudio.model.DefaultSubSurfaceConstructions':
        """
        Create a new DefaultSubSurfaceConstructions object.
        
        Returns:
            OpenStudio DefaultSubSurfaceConstructions object
        """
        return openstudio.model.DefaultSubSurfaceConstructions(self.model)
    
    def find_construction_by_name(self, name: str) -> Optional['openstudio.model.Construction']:
        """
        Find an existing construction in the model by name.
        
        Args:
            name: Construction name to search for
            
        Returns:
            Construction object if found, None otherwise
        """
        constructions = self.model.getConstructions()
        for construction in constructions:
            if construction.name().get() == name:
                return construction
        return None
    
    def create_construction(self, name: str) -> 'openstudio.model.Construction':
        """
        Create a construction based on ASHRAE standards data.
        
        This method looks up the construction in the JSON data files,
        finds the materials, and creates a real layered construction.
        
        Args:
            name: Construction name
            
        Returns:
            OpenStudio Construction object
        """
        # Check if construction already exists
        existing = self.find_construction_by_name(name)
        if existing:
            logger.debug(f"Found existing construction: {name}")
            return existing
        
        # Look up construction data in JSON
        construction_data = self.find_construction_data(name)
        if not construction_data:
            # Raise error if no construction data found
            raise (f"Construction data not found for '{name}'")
        
        # Create construction with materials from JSON data
        construction = openstudio.model.Construction(self.model)
        construction.setName(name)
        
        materials_list = construction_data.get('materials', [])
        if not materials_list:
            raise (f"No materials found for construction: {name}")
        
        # Create materials and add them as layers
        materials_created = []
        for material_name in materials_list:
            material = self._create_material_from_data(material_name)
            if material:
                materials_created.append(material)
                logger.debug(f"Added material '{material_name}' to construction '{name}'")
            else:
                logger.warning(f"Failed to create material '{material_name}' for construction '{name}'")
        
        # Add materials as layers to the construction
        for material in materials_created:
            construction.insertLayer(construction.numLayers(), material)
        
        logger.info(f"Created construction '{name}' with {len(materials_created)} materials")
        return construction

    def _load_constructions_data(self) -> Dict[str, Any]:
        """
        Load and cache the ASHRAE 90.1 constructions JSON data.
        
        Returns:
            Dictionary containing constructions data
        """
        if self._constructions_data is None:
            constructions_file = self._data_dir / "ashrae_90_1.constructions.json"
            try:
                with open(constructions_file, 'r') as f:
                    self._constructions_data = json.load(f)
                logger.debug(f"Loaded constructions data from {constructions_file}")
            except FileNotFoundError:
                logger.error(f"Constructions file not found: {constructions_file}")
                self._constructions_data = {"constructions": []}
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing constructions JSON: {e}")
                self._constructions_data = {"constructions": []}
        
        return self._constructions_data
    
    def _load_materials_data(self) -> Dict[str, Any]:
        """
        Load and cache the ASHRAE 90.1 materials JSON data.
        
        Returns:
            Dictionary containing materials data
        """
        if self._materials_data is None:
            materials_file = self._data_dir / "ashrae_90_1.materials.json"
            try:
                with open(materials_file, 'r') as f:
                    self._materials_data = json.load(f)
                logger.debug(f"Loaded materials data from {materials_file}")
            except FileNotFoundError:
                logger.error(f"Materials file not found: {materials_file}")
                self._materials_data = {"materials": []}
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing materials JSON: {e}")
                self._materials_data = {"materials": []}
        
        return self._materials_data
    
    def _load_construction_properties_data(self) -> Dict[str, Any]:
        """
        Load and cache the ASHRAE 90.1 construction properties JSON data.
        
        Returns:
            Dictionary containing construction properties data
        """
        if not hasattr(self, '_construction_properties_data') or self._construction_properties_data is None:
            properties_file = self._data_dir / f"ashrae_90_1_2013.construction_properties.json"
            try:
                with open(properties_file, 'r') as f:
                    self._construction_properties_data = json.load(f)
                logger.debug(f"Loaded construction properties data from {properties_file}")
            except FileNotFoundError:
                logger.error(f"Construction properties file not found: {properties_file}")
                self._construction_properties_data = {"construction_properties": []}
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing construction properties JSON: {e}")
                self._construction_properties_data = {"construction_properties": []}
        
        return self._construction_properties_data

    def find_construction_data(self, construction_name: str) -> Optional[Dict[str, Any]]:
        """
        Find construction data by name in the ASHRAE constructions JSON.
        
        Args:
            construction_name: Name of the construction to find
            
        Returns:
            Construction data dictionary if found, None otherwise
        """
        constructions_data = self._load_constructions_data()
        
        for construction in constructions_data.get("constructions", []):
            if construction.get("name") == construction_name:
                logger.debug(f"Found construction data for: {construction_name}")
                return construction
        
        logger.warning(f"Construction not found: {construction_name}")
        return None
    
    def find_material_data(self, material_name: str) -> Optional[Dict[str, Any]]:
        """
        Find material data by name in the ASHRAE materials JSON.
        
        Args:
            material_name: Name of the material to find
            
        Returns:
            Material data dictionary if found, None otherwise
        """
        materials_data = self._load_materials_data()
        
        for material in materials_data.get("materials", []):
            if material.get("name") == material_name:
                logger.debug(f"Found material data for: {material_name}")
                return material
        
        logger.warning(f"Material not found: {material_name}")
        return None

    def _create_material_from_data(self, material_name: str) -> Optional['openstudio.model.Material']:
        """
        Create an OpenStudio material object from JSON data.
        
        Args:
            material_name: Name of the material to create
            
        Returns:
            OpenStudio Material object or None if creation fails
        """
        # Check if material already exists in model
        existing_material = self._find_material_by_name(material_name)
        if existing_material:
            logger.debug(f"Found existing material: {material_name}")
            return existing_material
        
        # Look up material data
        material_data = self.find_material_data(material_name)
        if not material_data:
            logger.warning(f"Material data not found: {material_name}")
            return None
        
        material_type = material_data.get('material_type')
        if not material_type:
            logger.warning(f"Material type not specified for: {material_name}")
            return None
        
        try:
            if material_type == 'StandardOpaqueMaterial':
                return self._create_standard_opaque_material(material_name, material_data)
            elif material_type == 'MasslessOpaqueMaterial':
                return self._create_massless_opaque_material(material_name, material_data)
            elif material_type == 'Air':
                return self._create_air_gap_material(material_name, material_data)
            elif material_type == 'SimpleGlazing':
                return self._create_simple_glazing_material(material_name, material_data)
            elif material_type == 'StandardGlazing':
                return self._create_standard_glazing_material(material_name, material_data)
            elif material_type == 'Gas':
                return self._create_gas_material(material_name, material_data)
            else:
                logger.warning(f"Unsupported material type '{material_type}' for material: {material_name}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating material '{material_name}': {e}")
            return None
    
    def _find_material_by_name(self, name: str) -> Optional['openstudio.model.Material']:
        """Find an existing material in the model by name."""
        # Check standard opaque materials
        for material in self.model.getStandardOpaqueMaterials():
            if material.name().get() == name:
                return material
        
        # Check massless opaque materials
        for material in self.model.getMasslessOpaqueMaterials():
            if material.name().get() == name:
                return material
        
        # Check air gap materials
        for material in self.model.getAirGaps():
            if material.name().get() == name:
                return material
        
        # Check glazing materials
        for material in self.model.getSimpleGlazings():
            if material.name().get() == name:
                return material
        
        for material in self.model.getStandardGlazings():
            if material.name().get() == name:
                return material
        
        # Check gas materials
        for material in self.model.getGass():
            if material.name().get() == name:
                return material
        
        return None
    
    def _create_standard_opaque_material(self, name: str, data: Dict[str, Any]) -> 'openstudio.model.StandardOpaqueMaterial':
        """Create a StandardOpaqueMaterial from JSON data."""
        material = openstudio.model.StandardOpaqueMaterial(self.model)
        material.setName(name)
        
        # Required properties
        if data.get('roughness'):
            material.setRoughness(data['roughness'])
        
        # TODO - UPDATE ALL THESE CONVERSIONS TO USE OPENSTUDIO.CONVERT INSTEAD

        if data.get('thickness') is not None:
            material.setThickness(data['thickness'] * 0.0254)  # Convert inches to meters
        
        if data.get('conductivity') is not None:
            material.setConductivity(data['conductivity'] * 1.73073)  # Convert Btu*in/hr*ft2*R to W/m*K
        
        if data.get('density') is not None:
            material.setDensity(data['density'] * 16.0185)  # Convert lb/ft3 to kg/m3
        
        if data.get('specific_heat') is not None:
            material.setSpecificHeat(data['specific_heat'] * 4186.8)  # Convert Btu/lb*R to J/kg*K
        
        # Optional properties
        if data.get('thermal_absorptance') is not None:
            material.setThermalAbsorptance(data['thermal_absorptance'])
        
        if data.get('solar_absorptance') is not None:
            material.setSolarAbsorptance(data['solar_absorptance'])
        
        if data.get('visible_absorptance') is not None:
            material.setVisibleAbsorptance(data['visible_absorptance'])
        
        logger.debug(f"Created StandardOpaqueMaterial: {name}")
        return material
    
    def _create_massless_opaque_material(self, name: str, data: Dict[str, Any]) -> 'openstudio.model.MasslessOpaqueMaterial':
        """Create a MasslessOpaqueMaterial from JSON data."""
        material = openstudio.model.MasslessOpaqueMaterial(self.model)
        material.setName(name)
        
        # Required properties
        if data.get('roughness'):
            material.setRoughness(data['roughness'])
        
        # TODO - UPDATE ALL THESE CONVERSIONS TO USE OPENSTUDIO.CONVERT INSTEAD

        if data.get('resistance') is not None:
            material.setThermalResistance(data['resistance'] * 0.176)  # Convert hr*ft2*R/Btu to m2*K/W
        
        # Optional properties
        if data.get('thermal_absorptance') is not None:
            material.setThermalAbsorptance(data['thermal_absorptance'])
        
        if data.get('solar_absorptance') is not None:
            material.setSolarAbsorptance(data['solar_absorptance'])
        
        if data.get('visible_absorptance') is not None:
            material.setVisibleAbsorptance(data['visible_absorptance'])
        
        logger.debug(f"Created MasslessOpaqueMaterial: {name}")
        return material
    
    def _create_air_gap_material(self, name: str, data: Dict[str, Any]) -> 'openstudio.model.AirGap':
        """Create an AirGap material from JSON data."""
        material = openstudio.model.AirGap(self.model)
        material.setName(name)
        
        # TODO - UPDATE ALL THESE CONVERSIONS TO USE OPENSTUDIO.CONVERT INSTEAD

        if data.get('resistance') is not None:
            material.setThermalResistance(data['resistance'] * 0.176)  # Convert hr*ft2*R/Btu to m2*K/W
        
        logger.debug(f"Created AirGap: {name}")
        return material
    
    def _create_simple_glazing_material(self, name: str, data: Dict[str, Any]) -> 'openstudio.model.SimpleGlazing':
        """Create a SimpleGlazing material from JSON data."""
        material = openstudio.model.SimpleGlazing(self.model)
        material.setName(name)
        
        # TODO - UPDATE ALL THESE CONVERSIONS TO USE OPENSTUDIO.CONVERT INSTEAD

        if data.get('u_factor') is not None:
            material.setUFactor(data['u_factor'] * 5.67826)  # Convert Btu/hr*ft2*R to W/m2*K
        
        if data.get('solar_heat_gain_coefficient') is not None:
            material.setSolarHeatGainCoefficient(data['solar_heat_gain_coefficient'])
        
        if data.get('visible_transmittance') is not None:
            material.setVisibleTransmittance(data['visible_transmittance'])
        
        logger.debug(f"Created SimpleGlazing: {name}")
        return material
    
    def _create_standard_glazing_material(self, name: str, data: Dict[str, Any]) -> 'openstudio.model.StandardGlazing':
        """Create a StandardGlazing material from JSON data."""
        material = openstudio.model.StandardGlazing(self.model)
        material.setName(name)
        
        # Required properties
        if data.get('optical_data_type'):
            material.setOpticalDataType(data['optical_data_type'])
        
        # TODO - UPDATE ALL THESE CONVERSIONS TO USE OPENSTUDIO.CONVERT INSTEAD

        if data.get('thickness') is not None:
            material.setThickness(data['thickness'] * 0.0254)  # Convert inches to meters
        
        # Optional properties with defaults
        if data.get('solar_transmittance_at_normal_incidence') is not None:
            material.setSolarTransmittanceatNormalIncidence(data['solar_transmittance_at_normal_incidence'])
        
        if data.get('front_side_solar_reflectance_at_normal_incidence') is not None:
            material.setFrontSideSolarReflectanceatNormalIncidence(data['front_side_solar_reflectance_at_normal_incidence'])
        
        if data.get('back_side_solar_reflectance_at_normal_incidence') is not None:
            material.setBackSideSolarReflectanceatNormalIncidence(data['back_side_solar_reflectance_at_normal_incidence'])
        
        if data.get('visible_transmittance_at_normal_incidence') is not None:
            material.setVisibleTransmittanceatNormalIncidence(data['visible_transmittance_at_normal_incidence'])
        
        if data.get('front_side_visible_reflectance_at_normal_incidence') is not None:
            material.setFrontSideVisibleReflectanceatNormalIncidence(data['front_side_visible_reflectance_at_normal_incidence'])
        
        if data.get('back_side_visible_reflectance_at_normal_incidence') is not None:
            material.setBackSideVisibleReflectanceatNormalIncidence(data['back_side_visible_reflectance_at_normal_incidence'])
        
        if data.get('infrared_transmittance_at_normal_incidence') is not None:
            material.setInfraredTransmittanceatNormalIncidence(data['infrared_transmittance_at_normal_incidence'])
        
        if data.get('front_side_infrared_hemispherical_emissivity') is not None:
            material.setFrontSideInfraredHemisphericalEmissivity(data['front_side_infrared_hemispherical_emissivity'])
        
        if data.get('back_side_infrared_hemispherical_emissivity') is not None:
            material.setBackSideInfraredHemisphericalEmissivity(data['back_side_infrared_hemispherical_emissivity'])
        
        # TODO - UPDATE ALL THESE CONVERSIONS TO USE OPENSTUDIO.CONVERT INSTEAD

        if data.get('conductivity') is not None:
            material.setConductivity(data['conductivity'] * 1.73073)  # Convert Btu*in/hr*ft2*R to W/m*K
        
        if data.get('dirt_correction_factor_for_solar_and_visible_transmittance') is not None:
            material.setDirtCorrectionFactorforSolarandVisibleTransmittance(data['dirt_correction_factor_for_solar_and_visible_transmittance'])
        
        if data.get('solar_diffusing') is not None:
            material.setSolarDiffusing(data['solar_diffusing'])
        
        logger.debug(f"Created StandardGlazing: {name}")
        return material
    
    def _create_gas_material(self, name: str, data: Dict[str, Any]) -> 'openstudio.model.Gas':
        """Create a Gas material from JSON data."""
        material = openstudio.model.Gas(self.model)
        material.setName(name)
        
        if data.get('gas_type'):
            material.setGasType(data['gas_type'])
        
        # TODO - UPDATE ALL THESE CONVERSIONS TO USE OPENSTUDIO.CONVERT INSTEAD

        if data.get('thickness') is not None:
            material.setThickness(data['thickness'] * 0.0254)  # Convert inches to meters
        
        logger.debug(f"Created Gas: {name}")
        return material
    
    def find_construction_properties(self, climate_zone_set: str, intended_surface_type: str, 
                                   standards_construction_type: str, building_category: str) -> Optional[Dict[str, Any]]:
        """
        Find construction properties based on search criteria.
        
        This finds construction properties using the model_find_object logic for construction_properties.
        
        Args:
            climate_zone_set: Climate zone set (e.g., 'ClimateZone 4A')
            intended_surface_type: Surface type (e.g., 'ExteriorWall')
            standards_construction_type: Construction type (e.g., 'SteelFramed')
            building_category: Building category (e.g., 'Nonresidential')
            
        Returns:
            Construction properties dictionary if found, None otherwise
        """
        properties_data = self._load_construction_properties_data()
        
        # First search with full criteria
        search_criteria = {
            'climate_zone_set': climate_zone_set,
            'intended_surface_type': intended_surface_type,
            'standards_construction_type': standards_construction_type,
            'building_category': building_category
        }
        
        for props in properties_data.get("construction_properties", []):
            if all(props.get(key) == value for key, value in search_criteria.items()):
                logger.debug(f"Found construction properties: {props.get('construction')}")
                return props
        
        # Second search: Try with main climate zone (e.g., '4' instead of '4A')
        if len(climate_zone_set) > 1:
            climate_zone = climate_zone_set[:-1]  # Remove the letter suffix
            search_criteria['climate_zone_set'] = climate_zone
            
            for props in properties_data.get("construction_properties", []):
                if all(props.get(key) == value for key, value in search_criteria.items()):
                    logger.debug(f"Found construction properties with simplified climate zone: {props.get('construction')}")
                    return props
        
        # Third search: Legacy search without standards_construction_type
        search_criteria['climate_zone_set'] = climate_zone_set  # Reset to original
        del search_criteria['standards_construction_type']
        
        for props in properties_data.get("construction_properties", []):
            if all(props.get(key) == value for key, value in search_criteria.items()):
                logger.debug(f"Found construction properties (legacy search): {props.get('construction')}")
                return props
        
        logger.warning(f"Construction properties not found for: climate_zone_set={climate_zone_set}, "
                      f"intended_surface_type={intended_surface_type}, "
                      f"standards_construction_type={standards_construction_type}, "
                      f"building_category={building_category}")
        return None

    
   