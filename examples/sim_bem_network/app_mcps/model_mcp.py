import logging
import shutil
from enum import Enum
from pathlib import Path
from typing import Union

from mcp.server import FastMCP
from mcp.server.fastmcp.utilities.logging import get_logger

logging.basicConfig(
    filename="mcp_server.log",
    filemode="w",  # Overwrite each run
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = get_logger(__name__)

# counties_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'resources', 'counties.dat')

class BuildingType(str, Enum):
    MEDIUM_OFFICE = "MediumOffice"


class StandardType(str, Enum):
    ASHRAE_90_1_2019 = "90.1-2019"
    ASHRAE_90_1_2016 = "90.1-2016"

class ClimateZone(str, Enum):
    CLIMATEZONE2A = "ASHRAE169-2013-2A"
    CLIMATEZONE5A = "ASHRAE169-2013-5A"

def serve(host, port, transport):
    """Initialize and runs the agent cards mcp_servers server.
    Args:
        host: The hostname or IP address to bind the server to.
        port: The port number to bind the server to.
        transport: The transport mechanism for the MCP server (e.g., 'stdio', 'sse')

    Raises:
        ValueError
    """
    logger.info("Starting OpenStudio Modifier Server")
    mcp = FastMCP("agent-cards", host=host, port=port)

    @mcp.tool(
        name="get_climate_by_location",
        description="Get the climate zone by city and state"
    )
    def get_climate_by_location(city: str, state: str) -> str:
        """
        Get the climate zone by city or county and state
        :param city: name of the city, For example: "Boulder"
        :param state: name of the State, For example: "Colorado"
        :return: A climate zone string
        """
        if city.lower() == "tampa" and state.lower() == "florida":
            return ClimateZone.CLIMATEZONE2A.value
        return ClimateZone.CLIMATEZONE5A.value


    @mcp.tool(
        name="load_openstudio_model",
        description="Load and copy OpenStudio (.osm) building energy models based on building type, standard type, and climate zone"
    )
    def load_openstudio_model(building_type: 'BuildingType', standard_type: 'StandardType',
                                   climate_zone: 'ClimateZone', save_dir: str) -> Union[str, None]:
        """
        Load an openstudio model based on building type, standard type and climate zone

        :param building_type: BuildingType
        :param standard_type: StandardType
        :param climate_zone: ClimateZone
        :param save_dir: a local directory to save the loaded model
        :return: str - Path to the copied model file if successful, None if failed
        """
        try:
            # Create the model filename
            model_name = f"{building_type.value}-{standard_type.value}-{climate_zone.value}.osm"

            # Get the directory where this script is located
            script_dir = Path(__file__).parent
            # Define source path relative to script location
            source_path = script_dir / "models" / model_name

            # Check if source file exists
            if not source_path.exists():
                print(f"Error: Model file {source_path} does not exist")
                return None

            # Create save directory if it doesn't exist
            save_dir_path = Path(save_dir)
            save_dir_path.mkdir(parents=True, exist_ok=True)

            # Define destination path
            destination_path = save_dir_path / model_name

            # Copy the file
            shutil.copy2(source_path, destination_path)

            print(f"Successfully loaded model: {model_name}")
            print(f"Copied from: {source_path}")
            print(f"Copied to: {destination_path}")

            return str(destination_path)

        except Exception as e:
            print(f"Error loading OpenStudio model: {e}")
            return None

    logger.info(f"OpenStudio MCP Server at {host}:{port} and transport {transport}")
    mcp.run(transport=transport)