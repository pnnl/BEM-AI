import json
import logging
from enum import Enum
from pathlib import Path
from typing import List, Sequence

from mcp.server import FastMCP

import openstudio

from pydantic import BaseModel

from .ashrae_standard import ASHRAEBuildingType, ASHRAESpaceType, ASHRAETemplate, ASHRAEClimateZone, ASHRAEExampleBuildingTypes, ASHRAE901StandardsWithOpenStudio

# Configure logging
logger = logging.getLogger(__name__)

class ASHRAEGeometryFile(BaseModel):
    """
    Class representing an ASHRAE geometry file with building type and OpenStudio model
    """
    model_config = {"arbitrary_types_allowed": True}
    
    building_type: ASHRAEExampleBuildingTypes
    building_type_osm_file: openstudio.model.Model

class OpenStudioStandardsDatabaseServer:

    def get_default_geometry_osm(self, building_type_enum: ASHRAEExampleBuildingTypes) -> ASHRAEGeometryFile:
        """
        Load an OpenStudio model from local resources directory based on building type enum.

        Args:
            building_type_enum: ASHRAEExampleBuildingTypes enum value specifying which building type to load

        Returns:
            ASHRAEGeometryFile containing the building type and loaded OpenStudio model

        Raises:
            ValueError: If building type is not supported or OSM file cannot be loaded
            FileNotFoundError: If the corresponding OSM file is not found
        """
        
        filename = f"ASHRAE{building_type_enum.value}.osm"
        
        # Construct the full path to the OSM file
        resources_dir = Path(__file__).parent.parent / "resources" / "geometry_files"
        osm_file_path = resources_dir / filename
        
        # Check if file exists
        if not osm_file_path.exists():
            raise FileNotFoundError(f"OSM file not found: {osm_file_path}")
        
        # Load the OpenStudio model
        try:
            model_optional = openstudio.model.Model.load(str(osm_file_path))
            if model_optional.is_initialized():
                geom_model = model_optional.get()
            else:
                raise ValueError(f"Failed to load OpenStudio model from: {osm_file_path}")
        except Exception as e:
            raise ValueError(f"Error loading OpenStudio model from {osm_file_path}: {str(e)}")

        return ASHRAEGeometryFile(
            building_type=building_type_enum.value,
            building_type_osm_file=geom_model
        )
    

    def generate_default_ashrae_geometry_osm(self, building_type: ASHRAEExampleBuildingTypes, save_directory: Path) -> bool:

        """
        Load an OpenStudio model from local resources directory based on building type enum and saves
        it to the specified directory

        Args:
            building_type: ASHRAEExampleBuildingTypes enum value specifying which building type to load
            save_directory: Path value specifying which directory in which to save the resulting OSM

        Returns:
            Returns a boolean for whether or not the operation was successful

        Raises:
            ValueError: If building type is not supported or OSM file cannot be loaded
            FileNotFoundError: If the corresponding OSM file is not found
        """
        try:
            # Ensure the save directory exists
            save_directory.mkdir(parents=True, exist_ok=True)
            
            # Load the geometry using the existing method
            ashrae_geometry = self.get_default_geometry_osm(building_type)
            
            # Create the output filename based on building type
            output_filename = f"{building_type.value}.osm"
            output_path = save_directory / output_filename
            
            # Save the OpenStudio model to the specified directory
            success = ashrae_geometry.building_type_osm_file.save(str(output_path), True)
            
            if not success:
                raise ValueError(f"Failed to save OpenStudio model to: {output_path}")
            
            return True
            
        except Exception as e:
            # Re-raise the exception to maintain the documented behavior
            raise e

    def apply_construction_set_to_geometry(self, geometry_space_type: ASHRAEExampleBuildingTypes, template: ASHRAETemplate, 
                                         climate_zone: ASHRAEClimateZone, ashrae_building_type: ASHRAEBuildingType, 
                                         is_residential: bool = False, save_directory: Path = None) -> dict:
        """
        Load a default geometry model and apply ASHRAE 90.1 construction set to it.
        
        Args:
            geometry_space_type: Example building type for geometry loading
            template: ASHRAE template for construction set
            climate_zone: Climate zone for construction set
            ashrae_building_type: ASHRAE building type for construction set application
            is_residential: Whether the building is residential
            save_directory: Optional directory to save the model with construction set applied
        
        Returns:
            Dictionary containing operation results and model information
        """
        try:
            # Step 1: Load default geometry
            geometry_result = self.get_default_geometry_osm(geometry_space_type)
            model = geometry_result.building_type_osm_file
            
            # Get model info before applying construction set
            spaces = model.getSpaces()
            thermal_zones = model.getThermalZones()
            initial_construction_sets = model.getDefaultConstructionSets()
            
            # Step 2: Create ASHRAE standards instance and apply construction set
            standards = ASHRAE901StandardsWithOpenStudio(template.value)
            
            success = standards.model_add_construction_set(
                model=model,
                climate_zone=climate_zone,
                building_type=ashrae_building_type,
                is_residential=is_residential
            )
            
            # Get final construction set count
            final_construction_sets = model.getDefaultConstructionSets()
            
            # Step 3: Optionally save the model
            saved_path = None
            if save_directory and success:
                try:
                    save_directory.mkdir(parents=True, exist_ok=True)
                    output_filename = f"{geometry_space_type.value}_{template.value}_{climate_zone.value.replace(' ', '_')}.osm"
                    output_path = save_directory / output_filename
                    
                    save_success = model.save(str(output_path), True)
                    if save_success:
                        saved_path = str(output_path)
                except Exception as e:
                    logger.warning(f"Failed to save model: {str(e)}")
            
            return {
                "success": success,
                "geometry_space_type": geometry_space_type.value,
                "template": template.value,
                "climate_zone": climate_zone.value,
                "ashrae_building_type": ashrae_building_type.value,
                "is_residential": is_residential,
                "model_info": {
                    "spaces_count": len(spaces),
                    "thermal_zones_count": len(thermal_zones),
                    "initial_construction_sets": len(initial_construction_sets),
                    "final_construction_sets": len(final_construction_sets)
                },
                "saved_to": saved_path,
                "message": f"Successfully applied {template.value} construction set to {geometry_space_type.value} model for {ashrae_building_type.value} in {climate_zone.value}" if success else "Failed to apply construction set"
            }
            
        except Exception as e:
            raise e


def serve(host, port, transport):
    """Initialize and run the OpenStudio Standards MCP server.
    Args:
        host: The hostname or IP address to bind the server to.
        port: The port number to bind the server to.
        transport: The transport mechanism for the MCP server (e.g., 'stdio', 'sse')

    Raises:
        ValueError
    """
    logger.info("Starting OpenStudio Standards MCP Server")
    
    osstd_srv = OpenStudioStandardsDatabaseServer()
    mcp = FastMCP("osstd-mcp-server", host=host, port=port)

    @mcp.tool(
        name="generate_default_ashrae_geometry_osm",
        description="Load an OpenStudio model (OSM) from local resources directory based on " \
                    "building type enum and save it to the specified directory"
    )
    def generate_default_ashrae_geometry_osm(building_type: str, save_directory: str) -> str:
        """
        Load an OpenStudio model (OSM) from local resources directory based on 
        building type enum and save it to the specified directory

        Args:
            building_type: The building type to load geometry for
            save_directory: The absolute or relative directory path where the OSM file will be saved

        Returns:
            JSON string with operation results
        """
        try:
            # Convert string back to enum
            try:
                building_type_enum = ASHRAEBuildingType(building_type)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid building type: {building_type}. Valid options: {[bt.value for bt in ASHRAEBuildingType]}"
                })
            
            # Convert string to Path
            save_directory_path = Path(save_directory)
            
            # Generate and save the geometry
            success = osstd_srv.generate_default_ashrae_geometry_osm(building_type_enum, save_directory_path)
            
            # Create output filename for response
            output_filename = f"{building_type_enum.value}.osm"
            output_path = save_directory_path / output_filename
            
            response_data = {
                "success": success,
                "building_type": building_type_enum.value,
                "saved_to": str(output_path),
                "message": f"Successfully saved {building_type_enum.value} geometry to {output_path}"
            }
            
            return json.dumps(response_data, indent=2)
        except Exception as e:
            logger.error(f"Error in generate_default_ashrae_geometry_osm: {str(e)}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="get_default_geometry_osm",
        description="Load an OpenStudio model from local resources directory based on building type"
    )
    def get_default_geometry_osm(building_type: str) -> str:
        """
        Load an OpenStudio model from local resources directory based on building type

        Args:
            building_type: The building type to load geometry for

        Returns:
            JSON string with model information
        """
        try:
            # Convert string back to enum
            try:
                building_type_enum = ASHRAEExampleBuildingTypes(building_type)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid building type: {building_type}. Valid options: {[bt.value for bt in ASHRAEBuildingType]}"
                })
            
            # Get the geometry
            result = osstd_srv.get_default_geometry_osm(building_type_enum)
            
            # Get model info and raw OSM string
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
            
            return json.dumps(response_data, indent=2)
        except Exception as e:
            logger.error(f"Error in get_default_geometry_osm: {str(e)}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="get_available_space_types",
        description="Get a list of all available space types"
    )
    def get_available_space_types() -> str:
        """
        Get a list of all available space types

        Returns:
            JSON string with available space types
        """
        try:
            response_data = {
                "available_space_types": [space_type.value for space_type in ASHRAESpaceType],
                "total_count": len(ASHRAESpaceType)
            }
            return json.dumps(response_data, indent=2)
        except Exception as e:
            logger.error(f"Error in get_available_space_types: {str(e)}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="get_available_building_types",
        description="Get a list of all available building types for geometry loading"
    )
    def get_available_building_types() -> str:
        """
        Get a list of all available building types for geometry loading

        Returns:
            JSON string with available building types
        """
        try:
            response_data = {
                "available_building_types": [building_type.value for building_type in ASHRAEBuildingType],
                "total_count": len(ASHRAEBuildingType)
            }
            return json.dumps(response_data, indent=2)
        except Exception as e:
            logger.error(f"Error in get_available_building_types: {str(e)}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="get_available_geometry_files",
        description="Get a list of all available geometry files for loading"
    )
    def get_available_geometry_files() -> str:
        """
        Get a list of all available geometry files for loading

        Returns:
            JSON string with available geometry files
        """
        try:
            response_data = {
                "available_geometry_files": [geometry_type.value for geometry_type in ASHRAEExampleBuildingTypes],
                "total_count": len(ASHRAEExampleBuildingTypes)
            }
            return json.dumps(response_data, indent=2)
        except Exception as e:
            logger.error(f"Error in get_available_geometry_files: {str(e)}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="get_ashrae_enumeration_values",
        description="Get all available ASHRAE enumeration values (templates, building types, space types, climate zones)"
    )
    def get_ashrae_enumeration_values() -> str:
        """
        Get all available ASHRAE enumeration values (templates, building types, space types, climate zones)

        Returns:
            JSON string with all enumeration values
        """
        try:
            response_data = {
                "templates": [template.value for template in ASHRAETemplate],
                "building_types": [building_type.value for building_type in ASHRAEBuildingType],
                "space_types": [space_type.value for space_type in ASHRAESpaceType],
                "climate_zones": [climate_zone.value for climate_zone in ASHRAEClimateZone],
                "example_building_types": [example_type.value for example_type in ASHRAEExampleBuildingTypes],
                "counts": {
                    "templates": len(ASHRAETemplate),
                    "building_types": len(ASHRAEBuildingType),
                    "space_types": len(ASHRAESpaceType),
                    "climate_zones": len(ASHRAEClimateZone),
                    "example_building_types": len(ASHRAEExampleBuildingTypes)
                }
            }
            return json.dumps(response_data, indent=2)
        except Exception as e:
            logger.error(f"Error in get_ashrae_enumeration_values: {str(e)}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="set_default_construction_set",
        description="Apply ASHRAE 90.1 construction set to an OpenStudio model based on climate zone, building type, and space type"
    )
    def set_default_construction_set(openstudio_model: object, template: str, climate_zone: str, 
                                   building_type: str, space_type: str) -> str:
        """
        Apply ASHRAE 90.1 construction set to an OpenStudio model based on climate zone, building type, and space type

        Args:
            openstudio_model: The OpenStudio model object to apply the construction set to
            template: ASHRAE template (e.g., '90.1-2013')
            climate_zone: Climate zone string (e.g., 'ASHRAE 169-2013-4A')
            building_type: Building type (e.g., 'Office', 'RetailStandalone')
            space_type: Space type (e.g., 'OpenOffice', 'Classroom')

        Returns:
            JSON string with operation results
        """
        try:
            # Validate template
            try:
                ASHRAETemplate(template)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid template: {template}. Valid options: {[t.value for t in ASHRAETemplate]}"
                })
            
            # Validate climate zone
            try:
                ASHRAEClimateZone(climate_zone)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid climate zone: {climate_zone}. Valid options: {[cz.value for cz in ASHRAEClimateZone]}"
                })
            
            # Validate building type
            try:
                ASHRAEBuildingType(building_type)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid building type: {building_type}. Valid options: {[bt.value for bt in ASHRAEBuildingType]}"
                })
            
            # Validate space type
            try:
                ASHRAESpaceType(space_type)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid space type: {space_type}. Valid options: {[st.value for st in ASHRAESpaceType]}"
                })
            
            # Determine if it's residential based on space type (using enum values)
            is_residential = space_type in [ASHRAESpaceType.APARTMENT.value] or building_type in [ASHRAEBuildingType.HIGHRISE_APARTMENT.value, ASHRAEBuildingType.MIDRISE_APARTMENT.value]
            
            # Create ASHRAE standards instance with the specified template
            standard = ASHRAE901StandardsWithOpenStudio(template)
            
            # Apply construction set to the model
            success = standard.model_add_construction_set(
                openstudio_model, 
                climate_zone, 
                building_type,
                is_residential
            )
            
            response_data = {
                "success": success,
                "template": template,
                "climate_zone": climate_zone,
                "building_type": building_type,
                "space_type": space_type,
                "is_residential": is_residential,
                "message": f"Successfully applied {template} construction set for {building_type} - {space_type} in {climate_zone}" if success else "Failed to apply construction set"
            }
            
            return json.dumps(response_data, indent=2)
        except Exception as e:
            logger.error(f"Error in set_default_construction_set: {str(e)}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="generate_example_with_default_construction_set",
        description="Load a default geometry model and apply ASHRAE 90.1 construction set to it, optionally saving the result"
    )
    def generate_example_with_default_construction_set(building_geometry: str, template: str, 
                                                       climate_zone: str, ashrae_building_type: str,
                                                       is_residential: bool = False, 
                                                       save_directory: str = None) -> str:
        """
        Load a default geometry model and apply ASHRAE 90.1 construction set to it, optionally saving the result

        Args:
            building_geometry: The building geometry type to load
            template: ASHRAE template (e.g., '90.1-2013')
            climate_zone: Climate zone string (e.g., 'ASHRAE 169-2013-4A')
            ashrae_building_type: ASHRAE building type for construction set application
            is_residential: Whether the building is residential (default: False)
            save_directory: Optional directory path to save the model with construction set applied

        Returns:
            JSON string with operation results
        """
        try:
            # Validate building type for geometry
            try:
                building_type_enum = ASHRAEExampleBuildingTypes(building_geometry)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid building type: {building_geometry}. Valid options: {[bt.value for bt in ASHRAEExampleBuildingTypes]}"
                })
            
            # Validate template
            try:
                template_enum = ASHRAETemplate(template)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid template: {template}. Valid options: {[t.value for t in ASHRAETemplate]}"
                })
            
            # Validate climate zone
            try:
                climate_zone_enum = ASHRAEClimateZone(climate_zone)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid climate zone: {climate_zone}. Valid options: {[cz.value for cz in ASHRAEClimateZone]}"
                })
            
            # Validate ASHRAE building type
            try:
                ashrae_building_type_enum = ASHRAEBuildingType(ashrae_building_type)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid ASHRAE building type: {ashrae_building_type}. Valid options: {[bt.value for bt in ASHRAEBuildingType]}"
                })
            
            # Convert save_directory to Path if provided
            save_dir = Path(save_directory) if save_directory else None
            
            # Use the method to apply construction set
            response_data = osstd_srv.apply_construction_set_to_geometry(
                geometry_space_type=building_type_enum,
                template=template_enum,
                climate_zone=climate_zone_enum,
                ashrae_building_type=ashrae_building_type_enum,
                is_residential=is_residential,
                save_directory=save_dir
            )
            
            return json.dumps(response_data, indent=2)
        except Exception as e:
            logger.error(f"Error in generate_example_with_default_construction_set: {str(e)}")
            return json.dumps({"error": str(e)})

    logger.info(f"MCP Server at {host}:{port} with transport {transport}")
    mcp.run(transport=transport)
