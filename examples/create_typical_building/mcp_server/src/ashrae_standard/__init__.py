"""
ASHRAE Standard Package - Enumerations and Common Types

This module provides enumerations for ASHRAE 90.1 standards including
building types, space types, and ASHRAE templates.
"""

from enum import Enum
from typing import List


class ASHRAETemplate(Enum):
    """Enumeration of supported ASHRAE 90.1 templates"""
    ASHRAE_90_1_2004 = "90.1-2004"
    ASHRAE_90_1_2007 = "90.1-2007"
    ASHRAE_90_1_2010 = "90.1-2010"
    ASHRAE_90_1_2013 = "90.1-2013"
    ASHRAE_90_1_2016 = "90.1-2016"
    ASHRAE_90_1_2019 = "90.1-2019"

class ASHRAEExampleBuildingTypes(Enum):

    """Enumeration of example building types for testing"""
    COLLEGE = "College"
    COURTHOUSE = "Courthouse"
    FULL_SERVICE_RESTAURANT = "FullServiceRestaurant"
    HIGHRISE_APARTMENT = "HighriseApartment"
    HOSPITAL = "Hospital"
    LABORATORY = "Laboratory"
    LARGE_HOTEL = "LargeHotel"
    LARGE_OFFICE = "LargeOffice"
    MEDIUM_OFFICE = "MediumOffice"
    MIDRISE_APARTMENT = "MidriseApartment"
    OUTPATIENT = "Outpatient"
    PRIMARY_SCHOOL = "PrimarySchool"
    QUICK_SERVICE_RESTAURANT = "QuickServiceRestaurant"
    RETAIL_STANDALONE = "RetailStandalone"
    RETAIL_STRIPMALL = "RetailStripmall"
    SECONDARY_SCHOOL = "SecondarySchool"
    SMALL_HOTEL = "SmallHotel"
    SMALL_OFFICE = "SmallOffice"
    WAREHOUSE = "Warehouse"


class ASHRAEBuildingType(Enum):
    """
    Enumeration of ASHRAE 90.1 building types.
    
    These values are based on the actual building types found in ASHRAE 90.1 
    construction sets data (ashrae_90_1_2013.construction_sets.json).
    """
    ANY = "Any"
    COLLEGE = "College"
    COURTHOUSE = "Courthouse"
    FULL_SERVICE_RESTAURANT = "FullServiceRestaurant"
    HIGHRISE_APARTMENT = "HighriseApartment"
    HOSPITAL = "Hospital"
    LABORATORY = "Laboratory"
    LARGE_HOTEL = "LargeHotel"
    LARGE_OFFICE = "LargeOffice"
    MEDIUM_OFFICE = "MediumOffice"
    MIDRISE_APARTMENT = "MidriseApartment"
    OFFICE = "Office"
    OUTPATIENT = "Outpatient"
    PRIMARY_SCHOOL = "PrimarySchool"
    QUICK_SERVICE_RESTAURANT = "QuickServiceRestaurant"
    RETAIL = "Retail"
    SECONDARY_SCHOOL = "SecondarySchool"
    SMALL_HOTEL = "SmallHotel"
    SMALL_OFFICE = "SmallOffice"
    STRIP_MALL = "StripMall"
    SUPER_MARKET = "SuperMarket"
    WAREHOUSE = "Warehouse"
    
    @classmethod
    def get_values(cls) -> List[str]:
        """Get all building type values as a list of strings."""
        return [bt.value for bt in cls]


def map_building_type_to_geometry(building_type: ASHRAEBuildingType) -> ASHRAEExampleBuildingTypes:
    """
    Map ASHRAEBuildingType (used for construction sets) to ASHRAEExampleBuildingTypes 
    (used for geometry files).
    
    Args:
        building_type: ASHRAEBuildingType enum value
        
    Returns:
        ASHRAEExampleBuildingTypes enum value for loading geometry
        
    Raises:
        ValueError: If building type cannot be mapped to a geometry file
    """
    # Direct mappings (most building types map 1:1)
    direct_mappings = {
        ASHRAEBuildingType.COLLEGE: ASHRAEExampleBuildingTypes.COLLEGE,
        ASHRAEBuildingType.COURTHOUSE: ASHRAEExampleBuildingTypes.COURTHOUSE,
        ASHRAEBuildingType.FULL_SERVICE_RESTAURANT: ASHRAEExampleBuildingTypes.FULL_SERVICE_RESTAURANT,
        ASHRAEBuildingType.HIGHRISE_APARTMENT: ASHRAEExampleBuildingTypes.HIGHRISE_APARTMENT,
        ASHRAEBuildingType.HOSPITAL: ASHRAEExampleBuildingTypes.HOSPITAL,
        ASHRAEBuildingType.LABORATORY: ASHRAEExampleBuildingTypes.LABORATORY,
        ASHRAEBuildingType.LARGE_HOTEL: ASHRAEExampleBuildingTypes.LARGE_HOTEL,
        ASHRAEBuildingType.LARGE_OFFICE: ASHRAEExampleBuildingTypes.LARGE_OFFICE,
        ASHRAEBuildingType.MEDIUM_OFFICE: ASHRAEExampleBuildingTypes.MEDIUM_OFFICE,
        ASHRAEBuildingType.MIDRISE_APARTMENT: ASHRAEExampleBuildingTypes.MIDRISE_APARTMENT,
        ASHRAEBuildingType.OUTPATIENT: ASHRAEExampleBuildingTypes.OUTPATIENT,
        ASHRAEBuildingType.PRIMARY_SCHOOL: ASHRAEExampleBuildingTypes.PRIMARY_SCHOOL,
        ASHRAEBuildingType.QUICK_SERVICE_RESTAURANT: ASHRAEExampleBuildingTypes.QUICK_SERVICE_RESTAURANT,
        ASHRAEBuildingType.SECONDARY_SCHOOL: ASHRAEExampleBuildingTypes.SECONDARY_SCHOOL,
        ASHRAEBuildingType.SMALL_HOTEL: ASHRAEExampleBuildingTypes.SMALL_HOTEL,
        ASHRAEBuildingType.SMALL_OFFICE: ASHRAEExampleBuildingTypes.SMALL_OFFICE,
        ASHRAEBuildingType.WAREHOUSE: ASHRAEExampleBuildingTypes.WAREHOUSE,
    }
    
    # Special mappings for types that don't have exact geometry matches
    special_mappings = {
        ASHRAEBuildingType.RETAIL: ASHRAEExampleBuildingTypes.RETAIL_STRIPMALL,
        ASHRAEBuildingType.STRIP_MALL: ASHRAEExampleBuildingTypes.RETAIL_STRIPMALL,
        ASHRAEBuildingType.OFFICE: ASHRAEExampleBuildingTypes.MEDIUM_OFFICE,  # Default to medium office
    }
    
    # Check direct mappings first
    if building_type in direct_mappings:
        return direct_mappings[building_type]
    
    # Check special mappings
    if building_type in special_mappings:
        return special_mappings[building_type]
    
    # Handle unmapped types
    raise ValueError(
        f"Building type '{building_type.value}' cannot be mapped to a geometry file. "
        f"Available geometry types: {[bt.value for bt in ASHRAEExampleBuildingTypes]}"
    )


class ASHRAESpaceType(Enum):
    """
    Enumeration of ASHRAE 90.1 space types.
    
    These values are based on the actual space types found in ASHRAE 90.1 
    construction sets data (ashrae_90_1_2013.construction_sets.json).
    """
    ATTIC = "Attic"
    BULK = "Bulk"
    FINE = "Fine"
    GUEST_ROOM = "GuestRoom"
    OFFICE = "Office"
    PAT_ROOM = "PatRoom"
    PLENUM = "Plenum"
    
    @classmethod
    def get_values(cls) -> List[str]:
        """Get all space type values as a list of strings."""
        return [st.value for st in cls]


class ASHRAEClimateZone(Enum):
    """
    Enumeration of ASHRAE 169 climate zones commonly used in 90.1 standards.
    """
    CZ1A = "ASHRAE 169-2013-1A"
    CZ2A = "ASHRAE 169-2013-2A"
    CZ2B = "ASHRAE 169-2013-2B"
    CZ3A = "ASHRAE 169-2013-3A"
    CZ3B = "ASHRAE 169-2013-3B"
    CZ3C = "ASHRAE 169-2013-3C"
    CZ4A = "ASHRAE 169-2013-4A"
    CZ4B = "ASHRAE 169-2013-4B"
    CZ4C = "ASHRAE 169-2013-4C"
    CZ5A = "ASHRAE 169-2013-5A"
    CZ5B = "ASHRAE 169-2013-5B"
    CZ5C = "ASHRAE 169-2013-5C"
    CZ6A = "ASHRAE 169-2013-6A"
    CZ6B = "ASHRAE 169-2013-6B"
    CZ7A = "ASHRAE 169-2013-7A"
    CZ7B = "ASHRAE 169-2013-7B"
    CZ8A = "ASHRAE 169-2013-8A"
    
    @classmethod
    def get_values(cls) -> List[str]:
        """Get all climate zone values as a list of strings."""
        return [cz.value for cz in cls]


# Export commonly used items
__all__ = [
    'ASHRAETemplate',
    'ASHRAEExampleBuildingTypes',
    'ASHRAEBuildingType',
    'ASHRAESpaceType', 
    'ASHRAEClimateZone',
    'map_building_type_to_geometry'
]

# Import OpenStudio integration if available
try:
    from .ashrae_openstudio import ASHRAE901StandardsWithOpenStudio
    __all__.append('ASHRAE901StandardsWithOpenStudio')
except ImportError as e:
    # OpenStudio integration not available (likely missing openstudio package)
    import warnings
    warnings.warn(f"OpenStudio integration not available: {e}", ImportWarning)
    
    # Create a placeholder class that raises an informative error
    class ASHRAE901StandardsWithOpenStudio:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "OpenStudio integration is not available. "
                "Please install the openstudio package to use this functionality."
            )
