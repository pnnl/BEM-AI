"""
ASHRAE 90.1 Standards Python Implementation
Step 1: Core data structure and JSON loader

This module provides a Python implementation of ASHRAE 90.1 standards,
focusing on construction set functionality.
"""

import json
import os
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

# Import enum types
try:
    from . import ASHRAETemplate, ASHRAEBuildingType, ASHRAEClimateZone, ASHRAESpaceType
except ImportError:
    # Handle case when run directly
    from __init__ import ASHRAETemplate, ASHRAEBuildingType, ASHRAEClimateZone, ASHRAESpaceType

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ASHRAE901Standards:
    """
    Python implementation of ASHRAE 90.1 standards.
    
    This class loads and provides access to ASHRAE 90.1 standards data for 
    construction sets, climate zones, and related building envelope properties.
    """
    
    def __init__(self, template: str):
        """
        Initialize ASHRAE 90.1 Standards with a specific template.
        
        Args:
            template: ASHRAE template string (e.g., '90.1-2013', '90.1-2016', '90.1-2019')
        """
        self.template = template
        self.standards_data: Dict[str, List[Dict]] = {}
        self._validate_template()
        self.load_standards_database()
    
    def _validate_template(self):
        """Validate that the template is a supported ASHRAE 90.1 standard."""
        supported_templates = [template.value for template in ASHRAETemplate]
        if self.template not in supported_templates:
            raise ValueError(f"Template '{self.template}' not supported. "
                           f"Supported templates: {supported_templates}")
    
    # TODO -- perhaps do this using building energy data API instead.
    def load_standards_database(self, data_directories: Optional[List[str]] = None):
        """
        Load ASHRAE 90.1 standards JSON data files.
        
        Args:
            data_directories: Optional list of directories to load data from.
                             If None, uses the default standards data path.
        """
        logger.info(f"Loading ASHRAE Standards data for {self.template}")
        
        if data_directories is None:
            # Default path structure - use resources/standard_data
            base_path = Path(__file__).parent.parent.parent / "resources" / "standard_data"
            data_directories = [str(base_path)]
        
        # Load JSON files from each directory
        for data_dir in data_directories:
            if os.path.exists(data_dir):
                self._load_json_files_from_directory(data_dir)
            else:
                logger.warning(f"Data directory not found: {data_dir}")
        
        # Validate that essential data was loaded
        self._validate_loaded_data()
    
    def _load_json_files_from_directory(self, data_dir: str):
        """Load all JSON files from a directory."""
        data_path = Path(data_dir)
        json_files = list(data_path.glob("*.json"))
        
        logger.debug(f"Loading JSON files from {data_dir}")
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Process each key-value pair in the JSON
                for key, objects in data.items():
                    if isinstance(objects, list):
                        # Override template in inherited files to match instantiated template
                        for obj in objects:
                            if isinstance(obj, dict) and 'template' in obj:
                                obj['template'] = self.template
                        
                        if key in self.standards_data:
                            logger.debug(f"Overriding {key} with {json_file.name}")
                        else:
                            logger.debug(f"Adding {key} from {json_file.name}")
                        
                        self.standards_data[key] = objects
                
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading {json_file}: {e}")
    
    def _validate_loaded_data(self):
        """Validate that essential data was loaded."""
        required_keys = ['construction_sets', 'climate_zone_sets']
        missing_keys = [key for key in required_keys if key not in self.standards_data]
        
        if missing_keys:
            logger.warning(f"Missing required data keys: {missing_keys}")
        
        if not self.standards_data:
            raise RuntimeError(f"No standards data loaded for template {self.template}")
    
    def find_objects(self, hash_of_objects: List[Dict], search_criteria: Dict[str, Any]) -> List[Dict]:
        """
        Find all objects matching the search criteria.
        
        Python implementation of the model_find_objects method.
        
        Args:
            hash_of_objects: List of dictionaries to search through
            search_criteria: Dictionary of key-value pairs to match
            
        Returns:
            List of matching objects
        """
        matching_objects = []
        
        for obj in hash_of_objects:
            if self._object_matches_criteria(obj, search_criteria):
                matching_objects.append(obj)
        
        return matching_objects
    
    def find_object(self, hash_of_objects: List[Dict], search_criteria: Dict[str, Any]) -> Optional[Dict]:
        """
        Find the first object matching the search criteria.
        
        Python implementation of the model_find_object method.
        
        Args:
            hash_of_objects: List of dictionaries to search through
            search_criteria: Dictionary of key-value pairs to match
            
        Returns:
            First matching object or None if no match found
        """
        matching_objects = self.find_objects(hash_of_objects, search_criteria)
        
        if not matching_objects:
            logger.debug(f"Find object search returned no results. Search criteria: {search_criteria}")
            return None
        elif len(matching_objects) == 1:
            return matching_objects[0]
        else:
            logger.warning(f"Find object search returned {len(matching_objects)} results, "
                          f"returning the first one. Search criteria: {search_criteria}")
            return matching_objects[0]
    
    def _object_matches_criteria(self, obj: Dict, criteria: Dict[str, Any]) -> bool:
        """Check if an object matches the search criteria."""
        for key, value in criteria.items():
            if key not in obj:
                return False
            
            # Handle None/null values
            if value is None and obj[key] is not None:
                return False
            if value is not None and obj[key] is None:
                return False
            
            # Handle boolean conversion (uses "Yes"/"No" strings)
            if key == 'is_residential' and isinstance(value, bool):
                obj_value = obj[key]
                if isinstance(obj_value, str):
                    obj_bool = obj_value.lower() in ['yes', 'true', '1']
                    if obj_bool != value:
                        return False
                elif obj_value != value:
                    return False
            elif obj[key] != value:
                return False
        
        return True
    
    def find_climate_zone_set(self, climate_zone: ASHRAEClimateZone) -> Optional[str]:
        """
        Find the climate zone set name for a given climate zone.
        
        Args:
            climate_zone: ASHRAEClimateZone enum value
            
        Returns:
            Climate zone set name or None if not found
        """
        if 'climate_zone_sets' not in self.standards_data:
            logger.error("Climate zone sets data not loaded")
            return None
        
        for climate_set in self.standards_data['climate_zone_sets']:
            if climate_zone.value in climate_set.get('climate_zones', []):
                return climate_set['name']
        
        logger.warning(f"Climate zone '{climate_zone.value}' not found in any climate zone set")
        return None
    
    def find_construction_set(self, building_type: ASHRAEBuildingType, 
                            space_type: Optional[ASHRAESpaceType], is_residential: bool = False) -> Optional[Dict]:
        """
        Find a construction set based on the given criteria.
        
        This is the main interface method that demonstrates the search functionality.
        
        Args:
            building_type: ASHRAEBuildingType enum value
            space_type: ASHRAESpaceType enum value or None
            is_residential: Whether the building is residential
            
        Returns:
            Dictionary containing construction set data or None if not found
        """
        
        # First search with is_residential criteria
        search_criteria = {
            'template': self.template,
            'building_type': building_type.value,
            'is_residential': 'Yes' if is_residential else 'No'
        }
        
        # Only add space_type to search criteria if it's not None
        if space_type is not None:
            search_criteria['space_type'] = space_type.value
        
        construction_set = self.find_object(
            self.standards_data.get('construction_sets', []), 
            search_criteria
        )
        
        # If not found, try without is_residential criteria
        if not construction_set:
            del search_criteria['is_residential']
            construction_set = self.find_object(
                self.standards_data.get('construction_sets', []), 
                search_criteria
            )
        
        if not construction_set:
            space_type_value = space_type.value if space_type is not None else None
            logger.info(f"Construction set not found for: template={self.template}, "
                       f"building_type={building_type.value}, "
                       f"space_type={space_type_value}, is_residential={is_residential}")
        
        return construction_set
    
    def get_available_building_types(self) -> List[str]:
        """Get list of available building types."""
        if 'construction_sets' not in self.standards_data:
            return []
        
        building_types = set()
        for cs in self.standards_data['construction_sets']:
            if 'building_type' in cs and cs['building_type']:
                building_types.add(cs['building_type'])
        
        return sorted(list(building_types))
    
    def get_available_space_types(self, building_type: Optional[ASHRAEBuildingType] = None) -> List[str]:
        """Get list of available space types, optionally filtered by building type."""
        if 'construction_sets' not in self.standards_data:
            return []
        
        space_types = set()
        for cs in self.standards_data['construction_sets']:
            # Filter by building type if specified
            if building_type and cs.get('building_type') != building_type.value:
                continue
            
            if 'space_type' in cs and cs['space_type']:
                space_types.add(cs['space_type'])
        
        return sorted(list(space_types))
    
    def get_data_summary(self) -> Dict[str, int]:
        """Get a summary of loaded data."""
        summary = {}
        for key, data in self.standards_data.items():
            if isinstance(data, list):
                summary[key] = len(data)
        return summary


def main():
    """Simple example usage of the ASHRAE901Standards class."""
    print("ASHRAE 90.1 Standards Python Implementation")
    print("=" * 50)
    print("This is the main ASHRAE standards module.")
    print("For comprehensive testing and examples, run:")
    print("  python test_ashrae_standards.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
