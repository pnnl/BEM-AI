# ASHRAE 90.1 Standards Python Implementation

This directory contains a Python implementation of ASHRAE 90.1 standards for building construction sets, providing access to standardized building envelope data.

## 🎯 Goal

Provide a complete Python implementation of ASHRAE 90.1 standards functionality for creating building construction sets with proper data access patterns.

## 📁 Files Structure

```
ashrae_standard/
├── ashrae_standards.py          # Core ASHRAE standards implementation
├── ashrae_openstudio.py         # OpenStudio integration layer
├── __init__.py                  # Enums and common types
├── test_ashrae_standards.py     # Test suite
└── README.md                    # This file

../../../resources/standard_data/  # Standard data files location
├── ashrae_90_1.climate_zone_sets.json
├── ashrae_90_1_2013.construction_sets.json
├── ashrae_90_1_2013.construction_properties.json
├── ashrae_90_1.constructions.json
└── ashrae_90_1.materials.json
```

## 🚀 Quick Start

### Run the Test Suite
```bash
cd ashrae_standard
python test_ashrae_standards.py
```

This tests the core ASHRAE standards functionality with standard data from `resources/standard_data`.

### Use in Server Context
The main integration is through the MCP server in `../server.py`, which provides:
- `get_default_geometry_osm` - Load default geometry models
- `apply_construction_set_to_geometry` - Apply ASHRAE construction sets to geometry

## 🔧 Core Implementation: Data Structure

This implementation provides the foundation for ASHRAE 90.1 standards by creating:

### Key Classes

#### `ASHRAE901Standards` (in `ashrae_standards.py`)
The main Python implementation of ASHRAE 90.1 standards with methods:

- `__init__(template)` - Initialize with standards template (e.g., '90.1-2013')
- `load_standards_database()` - Loads JSON standards data
- `find_object(data, criteria)` - Find objects matching criteria
- `find_climate_zone_set(zone)` - Find climate zone sets
- `find_construction_set(...)` - Core construction set search functionality

#### `ASHRAE901StandardsWithOpenStudio` (in `ashrae_openstudio.py`)
Extended class with OpenStudio integration:

- `model_add_construction_set(model, ...)` - Add construction sets to OpenStudio models
- `create_construction_set(...)` - Create OpenStudio construction set objects
- `apply_construction_set_to_model(...)` - Apply construction sets to existing models

#### Enumerations (in `__init__.py`)
- `ASHRAETemplate` - Supported ASHRAE templates
- `ASHRAEExampleBuildingTypes` - Example building types for geometry loading
- `ASHRAEBuildingType` - ASHRAE building types from standards data
- `ASHRAEClimateZone` - ASHRAE 169 climate zones
- `ASHRAESpaceType` - ASHRAE space types

### Key Functionality Demonstrated

1. **JSON Data Loading**: Loads ASHRAE 90.1 standards data from JSON files
2. **Climate Zone Mapping**: Maps climate zones to climate zone sets
3. **Construction Set Search**: Finds appropriate construction sets based on:
   - Template (e.g., '90.1-2013')
   - Climate zone (e.g., 'ASHRAE 169-2013-4A')
   - Building type (e.g., 'Office')
   - Space type (e.g., 'OpenOffice')
   - Residential flag

## 📊 API Reference

| Method | Description |
|--------|-------------|
| `ASHRAE901Standards('90.1-2013')` | Initialize standards with template |
| `std.find_object(data, criteria)` | Find object matching criteria |
| `std.find_climate_zone_set(zone)` | Find climate zone set for zone |
| `std.standards_data['construction_sets']` | Access construction set data |

## 🧪 Example Usage

### Basic Standards Usage
```python
from ashrae_standards import ASHRAE901Standards
from ashrae_standard import ASHRAETemplate, ASHRAEClimateZone, ASHRAEBuildingType

# Create standards object
std = ASHRAE901Standards(ASHRAETemplate.ASHRAE_90_1_2013.value)

# Find construction set
construction_set = std.find_construction_set(
    climate_zone=ASHRAEClimateZone.CZ4A.value,
    building_type=ASHRAEBuildingType.OFFICE.value,
    space_type='Office',
    is_residential=False
)

if construction_set:
    print(f"Found construction set: {construction_set['name']}")
```

### OpenStudio Integration
```python
from ashrae_standard import ASHRAE901StandardsWithOpenStudio
import openstudio

# Create OpenStudio model
model = openstudio.Model()

# Create standards object with OpenStudio integration
std = ASHRAE901StandardsWithOpenStudio(ASHRAETemplate.ASHRAE_90_1_2013.value)

# Add construction set to model
construction_set = std.model_add_construction_set(
    model=model,
    climate_zone=ASHRAEClimateZone.CZ4A,
    building_type=ASHRAEBuildingType.OFFICE,
    is_residential=False
)
```

## 📋 Current Status

The implementation provides:

✅ **Core Standards Implementation**: Complete ASHRAE 90.1 standards data loading and querying  
✅ **OpenStudio Integration**: Full OpenStudio model creation and construction set application  
✅ **MCP Server Integration**: Available through server endpoints for geometry and construction sets  
✅ **Comprehensive Testing**: Test suite covering all major functionality  
✅ **Type Safety**: Full enum-based type system for templates, building types, and climate zones  

## 🔄 Integration Points

### Server Integration
The ASHRAE standards are fully integrated into the MCP server (`../server.py`):
- `get_default_geometry_osm()` - Load default ASHRAE geometry models
- `apply_construction_set_to_geometry()` - Apply construction sets to loaded geometry

### Available Tools
- Construction set application to existing OpenStudio models
- Default geometry loading for 17 different building types
- Climate zone and building type validation
- Comprehensive error handling and logging

## 📚 Dependencies

### Core Implementation
- Python 3.8+
- Standard library (json, pathlib, logging, typing)

### OpenStudio Integration
- `openstudio` Python package
- OpenStudio Python bindings

### Server Integration
- `mcp` (Model Context Protocol) package
- Additional server dependencies as defined in `pyproject.toml`

## 📂 Data Directory Structure

The implementation uses a centralized data directory structure:

- **Standard Data**: `../../../resources/standard_data/` - Contains the ASHRAE 90.1 JSON data files

The code automatically loads data from the `resources/standard_data` directory, making it easier to manage and update standard data files across the project.

## 🎯 Key Achievements

1. **Complete Implementation**: Fully functional ASHRAE 90.1 standards implementation with OpenStudio integration
2. **MCP Server Integration**: Available through Model Context Protocol server endpoints
3. **Type Safety**: Comprehensive enum-based type system for all ASHRAE parameters
4. **Production Ready**: Tested and validated implementation with error handling
5. **Extensible Architecture**: Modular design supporting future enhancements

## 💡 Architecture Overview

The implementation follows a layered architecture:

1. **Data Layer** (`ashrae_standards.py`): JSON data loading and standards querying
2. **Integration Layer** (`ashrae_openstudio.py`): OpenStudio model creation and manipulation
3. **Type Layer** (`__init__.py`): Enum definitions and type safety
4. **Server Layer** (`../server.py`): MCP protocol implementation and API endpoints

This architecture ensures separation of concerns while providing a cohesive API for ASHRAE standards functionality.
