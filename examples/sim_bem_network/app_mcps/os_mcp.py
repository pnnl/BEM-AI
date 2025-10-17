import logging
import math
import os
import shutil
import subprocess
from datetime import datetime

import openstudio
from mcp.server import FastMCP
from mcp.server.fastmcp.utilities.logging import get_logger
from openstudio import BoundingBox, Point3d, Transformation
from openstudio.openstudiomodelgeometry import DaylightingControl

logging.basicConfig(
    filename="mcp_server.log",
    filemode="w",  # Overwrite each run
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = get_logger(__name__)

OPENSTUDIOCLI = "/Applications/OpenStudio-3.10.0/bin/openstudio"

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
        name="modify_window_to_wall_ratio",
        description="Load an openstudio energy model, modify envelope window to wall ratio, save the modified model and return its local directory.",
    )
    def modify_window_to_wall_ratio(os_model_path: str, fraction_reduction: float) -> str:
        """
            Load an Openstudio model at os_model_path and reduce envelope window to wall ratio by a percent_reduction
            :param os_model_path: a valid path to an openstudio model (.osm):
            :param fraction_reduction: float, must be within 0 - 1
            :return: string, the path to a copied model that has the modified content.
        """
        translator = openstudio.openstudioosversion.VersionTranslator()
        model = translator.loadModel(os_model_path).get()
        model_copy = model.clone().to_Model()
        for subsurface in model_copy.getSubSurfaces():
            if subsurface.subSurfaceType() != "Skylight":
                scale_factor = math.sqrt(1 - fraction_reduction)
                # Get the centroid (Point3d)
                g = subsurface.centroid()
                # Create an array to collect the new vertices
                new_vertices = []
                # Loop on vertices (Point3ds)
                for vertext in subsurface.vertices():
                    # Point3d - Point3d = Vector3d
                    # Vector from centroid to vertext (GA, GB, GC, etc)
                    centroid_vector = vertext - g
                    # Resize the vector (done in place) accordig to scale_factor
                    centroid_vector.setLength(centroid_vector.length() * scale_factor)
                    # Move the vertext toward the centroid
                    vertext = g + centroid_vector
                    new_vertices.append(vertext)

                subsurface.setVertices(new_vertices)
        # Modify the file path to save the modified model
        new_path = os_model_path.replace('.osm', '_copy.osm')
        # Save the model_copy to the new path
        model_copy.save(new_path, True)  # Save with overwriting permission
        return new_path

    @mcp.tool(
        name="add_daylight_sensor",
        description="Add a daylighting sensor to spaces and save the model to an output directory"
    )
    def add_daylight_sensors_test(os_model_path: str) -> dict[str, str]:
        """
        Add daylight sensors to spaces that contains access to exterior fenestration

        :param os_model_path: str local directory of the openstudio model
        :return: dict: a dictionary, key represents space name and value represents status
        """

        def has_subsurface(space):
            has = False
            for surface in space.surfaces():
                if surface.subSurfaces():
                    has = True
                    break
            return has

        translator = openstudio.openstudioosversion.VersionTranslator()
        model = translator.loadModel(os_model_path).get()
        model_copy = model.clone().to_Model()
        for space in model_copy.getSpaces():
            space_name = space.name()
            if has_subsurface(space):
                # space is perimeter space
                daylight_sensor = DaylightingControl(model_copy)
                daylight_sensor.setSpace(space)
                sensor_name = f"{space_name} Daylight Sensor"
                daylight_sensor.setName(sensor_name)
                # place sensors to the center of floor
                floor_surfaces = []
                for surface in space.surfaces():
                    if surface.surfaceType() == "Floor":
                        floor_surfaces.append(surface)

                bounding_box = BoundingBox()
                for floor in floor_surfaces:
                    bounding_box.addPoints(floor.vertices())

                xmin = bounding_box.minX().get()
                ymin = bounding_box.minY().get()
                zmin = bounding_box.minZ().get()
                xmax = bounding_box.maxX().get()
                ymax = bounding_box.maxY().get()

                x_pos = (xmin + xmax) / 2
                y_pos = (ymin + ymax) / 2
                z_pos = zmin + 1.0

                new_point = Point3d(x_pos, y_pos, z_pos)
                on_surface = False
                # check if the point is on the floors
                for floor in floor_surfaces:
                    # check if sensor is on floor plane
                    plane = floor.plane()
                    point_on_plane = plane.project(new_point)

                    face_transform = Transformation.alignFace(floor.vertices())
                    face_vertices = list(face_transform * floor.vertices())
                    face_point_on_plane = face_transform * point_on_plane
                    if openstudio.pointInPolygon(face_point_on_plane, face_vertices[::-1], 0.01):
                        on_surface = True

                if on_surface:
                    daylight_sensor.setPosition(new_point)
                    daylight_sensor.setPhiRotationAroundZAxis(0.0)
                    daylight_sensor.setIlluminanceSetpoint(430.0)
                    daylight_sensor.setLightingControlType('Continuous')
                    daylight_sensor.setMinimumInputPowerFractionforContinuousDimmingControl(0.3)
                    daylight_sensor.setMinimumLightOutputFractionforContinuousDimmingControl(0.2)
                    daylight_sensor.setNumberofSteppedControlSteps(1)
        # Modify the file path to save the modified model
        new_path = os_model_path.replace('.osm', '_copy.osm')
        # Save the model_copy to the new path
        model_copy.save(new_path, True)
        return new_path

    @mcp.tool(
        name="run_openstudio_simulation",
        description="Load an openstudio energy model, and start an simulation",
    )
    def run_openstudio_model_simulation(os_model_path: str) -> bool:
        # Extract the directory and file name from os_model_path
        model_dir, model_filename = os.path.split(os_model_path)
        # Remove the file extension from model_filename
        model_name, _ = os.path.splitext(model_filename)
        # Create the run_dir path
        run_dir = os.path.join(model_dir, f"{model_name}_run")
        # Remove the directory if it exists, then create a new one
        if os.path.exists(run_dir):
            shutil.rmtree(run_dir)
        # Ensure the directory exists
        os.makedirs(run_dir)

        translator = openstudio.openstudioosversion.VersionTranslator()
        model = translator.loadModel(os_model_path).get()

        idf_name = "in.idf"
        osm_name = "in.osm"
        osw_name = "in.osw"
        openstudio.logFree(
            openstudio.Debug,
            "openstudio.model.Model",
            f"Starting simulation here: {run_dir}.",
        )
        openstudio.logFree(
            openstudio.Info,
            "openstudio.model.Model",
            f"Started simulation {run_dir} at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}.",
        )
        forward_translator = openstudio.energyplus.ForwardTranslator()
        idf = forward_translator.translateModel(model)
        idf_path = openstudio.path(f"{run_dir}/{idf_name}")
        osm_path = openstudio.path(f"{run_dir}/{osm_name}")
        osw_path = openstudio.path(f"{run_dir}/{osw_name}")
        idf.save(idf_path, True)
        model.save(osm_path, True)

        # set up the simulation
        # close current sql file
        model.resetSqlFile()
        # need to add wrapper here
        epw_path = model.weatherFile().get().url().get()

        workflow = openstudio.WorkflowJSON()
        # copy the weather file to this directory
        epw_name = os.path.basename(epw_path)
        try:
            shutil.copy(epw_path, os.path.join(run_dir, epw_name))
        except Exception as e:
            openstudio.logFree(
                openstudio.Error,
                "openstudio.model.Model",
                "Due to limitations on Windows file path lengths, this measure won't work unless your project is located in a directory whose filepath is less than 90 characters long, including slashes.",
            )

        workflow.setSeedFile(osm_name)
        workflow.setWeatherFile(epw_name)
        workflow.saveAs(os.path.abspath(str(osw_path)))

        cmd = f'"{OPENSTUDIOCLI}" run -w "{osw_path}"'

        process = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout_str, stderr_str = process.communicate()
        status = process.returncode

        if status != 0:
            # failed
            openstudio.logFree(
                openstudio.Error,
                "openstudio.standards.command",
                f"Error running command: '#{cmd}'",
            )
            raise ValueError(f"Error running command: '#{cmd}'")

        sql_path = openstudio.path(os.path.join(run_dir, "run", "eplusout.sql"))

        if openstudio.exists(sql_path):
            sql = openstudio.SqlFile(sql_path)
            # Check to make sure the sql file is readable,
            # which won't be true if EnergyPlus crashed during simulation
            if not sql.connectionOpen():
                openstudio.logFree(
                    openstudio.Error,
                    "openstudio.model.Model",
                    f"The run failed, cannot create model.  Look at the eplusout.err file in #{run_dir} to see the cause.",
                )
                raise ValueError(
                    f"The run failed, cannot create model.  Look at the eplusout.err file in #{run_dir} to see the cause."
                )
            # Attach the sql file from the run to the model
            model.setSqlFile(sql)
        else:
            # If the sql file does not exist, it is likely that EnergyPlus crashed,
            # in which case the useful errors are inside the eplusout.err file
            err_file_default_path = os.path.join(run_dir, "run", "eplusout.err")
            err_file_os_path = openstudio.path(err_file_default_path)
            if openstudio.exists(err_file_os_path):
                with open(err_file_default_path, "r") as file:
                    errs = file.read()
                openstudio.logFree(
                    openstudio.Error,
                    "openstudio.model.Model",
                    f"The run did not finish because of the following errors: #{errs}",
                )
                raise ValueError(
                    f"The run did not finish because of the following errors: #{errs}"
                )
            else:
                openstudio.logFree(
                    openstudio.Error,
                    "openstudio.model.Model",
                    f"Results for the run couldn't be found here: #{sql_path}.",
                )
                raise ValueError(
                    f"Results for the run couldn't be found here: #{sql_path}."
                )

        # Report severe or fatal errors in the run
        error_query = "SELECT ErrorMessage FROM Errors WHERE ErrorType in(1,2)"
        errs = model.sqlFile().get().execAndReturnVectorOfString(error_query)
        if errs.is_initialized():
            errs = errs.get()

        # Check that the run completed successfully
        end_file_default_path = os.path.join(run_dir, "run", "eplusout.end")
        end_file_os_path = openstudio.path(end_file_default_path)
        if openstudio.exists(end_file_os_path):
            with open(end_file_default_path, "r") as file:
                endstring = file.read()

        if "EnergyPlus Completed Successfully" not in endstring:
            openstudio.logFree(
                openstudio.Error,
                "openstudio.model.Model",
                f"The run did not finish and had following errors: #{errs}",
            )
            raise ValueError(
                f"The run did not finish and had following errors: #{errs}"
            )

        # Log any severe errors that did not cause simulation to fail
        if not len(errs) == 0:
            openstudio.logFree(
                openstudio.Error,
                "openstudio.model.Model",
                f"The run completed but had the following severe errors: #{errs}",
            )

        return True

    @mcp.tool(
        name="retrieve_openstudio_model_annual_site_eui",
        description="Retrieve model annual site energy use intensity (EUI)",
    )
    def retrieve_openstudio_model_annual_site_eui(os_model_path: str) -> dict:
        """
        Read the simulation's annual site EUI
        :param os_model_path: [str] file path
        :return: EnergyUseIntensityInfo
        """
        translator = openstudio.openstudioosversion.VersionTranslator()
        model = translator.loadModel(os_model_path).get()

        ## Getting the sql file
        # Extract the directory and file name from os_model_path
        model_dir, model_filename = os.path.split(os_model_path)
        # Remove the file extension from model_filename
        model_name, _ = os.path.splitext(model_filename)
        # Create the run_dir path
        run_dir = os.path.join(model_dir, f"{model_name}_run")
        sql_path = openstudio.path(os.path.join(run_dir, "run", "eplusout.sql"))
        if openstudio.exists(sql_path):
            sql_file = openstudio.SqlFile(sql_path)

            total_site_energy_kbtu = round(openstudio.convert(sql_file.totalSiteEnergy().get(), 'GJ', 'kBtu').get(), 2)
            floor_area_ft2 = round(openstudio.convert(model.getBuilding().floorArea(), 'm^2', 'ft^2').get(), 2)
            site_eui_kbtu_per_ft2 = round(total_site_energy_kbtu / floor_area_ft2, 2)

            return {
                "status": "success",
                "site_eui_kbtu_per_ft2": site_eui_kbtu_per_ft2,
                "floor_area_ft2": floor_area_ft2,
                "total_site_energy_kbtu": total_site_energy_kbtu
            }
        else:
            return {
                "status": "failed",
                "message": "Cannot find the simulated results.",
                "site_eui_kbtu_per_ft2": 0.0,
                "floor_area_ft2": 0.0,
                "total_site_energy_kbtu": 0.0
            }

    logger.info(f"OpenStudio MCP Server at {host}:{port} and transport {transport}")
    mcp.run(transport=transport)