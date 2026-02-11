# OSSTD MCP Server

A Model Context Protocol (MCP) server that provides OpenStudio Standards Database tools for creating typical building models with ASHRAE 90.1 construction sets.

## Overview

This repository is a proof-of-concept MCP server that exposes OpenStudio Standards functionality through the Model Context Protocol. It currently focuses on ASHRAE 90.1 standards and provides capabilities to:

- Load pre-defined building geometry models for various building types
- Apply ASHRAE 90.1 construction sets based on climate zone and building type
- Generate OpenStudio models (.osm files) for energy simulation

The ultimate goal is to develop a comprehensive suite of tools that replicate the capabilities of the [CreateTypicalBuilding measure](https://github.com/NREL/openstudio-standards/blob/master/lib/openstudio-standards/create_typical/create_typical.rb) from the OpenStudio Standards library.

## Features

### Available Building Types
The server includes pre-defined geometry models for the following building types:
- College
- Courthouse
- FullServiceRestaurant
- HighriseApartment
- Hospital
- Laboratory
- LargeHotel
- LargeOffice
- MediumOffice
- MidriseApartment
- Outpatient
- PrimarySchool
- QuickServiceRestaurant
- RetailStripmall
- SecondarySchool
- SmallHotel
- SmallOffice

### ASHRAE 90.1 Standards Support
- **Templates**: 90.1-2004, 90.1-2007, 90.1-2010, 90.1-2013, 90.1-2016, 90.1-2019
- **Climate Zones**: All ASHRAE 169-2013 climate zones (1A through 8A)
- **Construction Sets**: Automatic application based on building type and climate zone

## Installation

### Prerequisites
- Python 3.12 or higher
- [OpenStudio](https://openstudio.net/) SDK 3.10.0 or higher

### Setup
1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd osstd-mcp-server
   ```

2. Install dependencies using uv (recommended):
   ```bash
   uv sync
   ```

   Or create a virtual environment and install with pip:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e .
   ```

3. Run the server:
   ```bash
   python -m src
   ```

## MCP Tools

The server provides the following tools through the Model Context Protocol:

### 1. `get_available_space_types`
Get a list of all available space types for ASHRAE standards.

### 2. `get_available_building_types`
Get a list of all available building types for geometry loading.

### 3. `get_available_geometry_files`
Get a list of all available pre-defined geometry files.

### 4. `get_ashrae_enumeration_values`
Get all available ASHRAE enumeration values including:
- Templates (90.1-2004 through 90.1-2019)
- Building types
- Space types
- Climate zones

### 5. `get_default_geometry_osm`
Load an OpenStudio model from the local resources directory based on building type.

**Parameters:**
- `building_type` (required): Building type from available options

**Example:**
```json
{
  "building_type": "LargeOffice"
}
```

### 6. `generate_default_ashrae_geometry_osm`
Load an OpenStudio model and save it to a specified directory.

**Parameters:**
- `building_type` (required): Building type from available options
- `save_directory` (required): Directory path where the OSM file will be saved

**Example:**
```json
{
  "building_type": "LargeOffice",
  "save_directory": "./output"
}
```

### 7. `generate_example_with_default_construction_set`
Load a default geometry model and apply ASHRAE 90.1 construction set to it.

**Parameters:**
- `building_geometry` (required): Building geometry type for loading (e.g., "LargeOffice"). Use get_available_geometry_files to get a complete list of available files.
- `template` (required): ASHRAE template (e.g., "90.1-2013")
- `climate_zone` (required): Climate zone (e.g., "ASHRAE 169-2013-4A")
- `ashrae_building_type` (required): ASHRAE building type for construction set
- `is_residential` (optional): Whether building is residential (default: false)
- `save_directory` (optional): Directory to save the resulting model

**Example:**
```json
{
  "building_geometry": "LargeOffice",
  "template": "90.1-2013",
  "climate_zone": "ASHRAE 169-2013-4A",
  "ashrae_building_type": "LargeOffice",
  "save_directory": "./output"
}
```

### 8. `set_default_construction_set`
Apply ASHRAE 90.1 construction set to an existing OpenStudio model.

**Parameters:**
- `openstudio_model` (required): OpenStudio model object
- `template` (required): ASHRAE template
- `climate_zone` (required): Climate zone
- `building_type` (required): Building type
- `space_type` (required): Space type

## Project Structure

```
osstd-mcp-server/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── server.py                    # Main MCP server implementation
│   ├── openstudio_model_wrapper.py  # OpenStudio model utilities
│   └── ashrae_standard/
│       ├── __init__.py              # ASHRAE enumerations
│       ├── ashrae_standards.py      # ASHRAE standards implementation
│       └── ashrae_openstudio.py     # OpenStudio integration
├── resources/
│   ├── geometry_files/              # Pre-defined building geometry files
│   │   ├── ASHRAELargeOffice.osm
│   │   ├── ASHRAESmallOffice.osm
│   │   └── ... (other building types)
│   └── standard_data/               # ASHRAE standards JSON data
│       ├── ashrae_90_1_2013.construction_sets.json
│       ├── ashrae_90_1.constructions.json
│       └── ... (other standards data)
├── tests/                           # Test files
├── pyproject.toml                   # Project configuration
└── README.md
```

## Usage Examples

### Basic Geometry Loading
```python
# Get available building types
result = mcp_client.call_tool("get_available_building_types")

# Load a large office geometry model
result = mcp_client.call_tool("get_default_geometry_osm", {
    "building_type": "LargeOffice"
})
```

### Construction Set Application
```python
# Apply ASHRAE 90.1-2013 construction set to a large office in climate zone 4A
result = mcp_client.call_tool("generate_example_with_default_construction_set", {
    "building_geometry": "LargeOffice",
    "template": "90.1-2013",
    "climate_zone": "ASHRAE 169-2013-4A",
    "ashrae_building_type": "LargeOffice",
    "save_directory": "./output"
})
```

## Development Status

This is a proof-of-concept implementation focusing on:
- ✅ Loading pre-defined building geometry models
- ✅ Applying ASHRAE 90.1 construction sets
- ✅ Basic MCP server functionality
- ✅ Support for multiple ASHRAE templates and climate zones

Future development will expand towards the full CreateTypicalBuilding measure capabilities including:
- [ ] Dynamic geometry generation
- [ ] Space type assignments
- [ ] HVAC system selection and sizing
- [ ] Internal load schedules
- [ ] Advanced construction set customization

## License

[ TBD ]

## Related Projects

- [OpenStudio Standards](https://github.com/NREL/openstudio-standards) - The original Ruby implementation
- [OpenStudio SDK](https://openstudio.net/) - The core OpenStudio software development kit
- [Model Context Protocol](https://modelcontextprotocol.io/) - The protocol specification