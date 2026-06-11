# OpenStudio Python SDK Experience Notes

This note summarizes source-backed OpenStudio Python SDK patterns reviewed from
adjacent building-modeling repositories.

The goal is to preserve practical SDK usage examples that can teach agents how
to draft model-inspection and model-editing scripts. These examples are
observed from working project code; do not infer broader SDK behavior beyond the
patterns shown here without checking the SDK or asking a human reviewer.

## Review Coverage

I scanned every Python file with a direct `import openstudio` or
`from openstudio ...` import in both source repositories and grouped repeated
patterns instead of repeating identical material/construction boilerplate.

One reviewed repository concentrates OpenStudio usage in model wrapper,
standards integration, server, setup, and OpenStudio-dependent test modules.
Another reviewed repository spans director, model assembly, modules,
component factories, material components, construction components, general
geometry components, HVAC components, and utility modules. Repeated material
classes follow the same `StandardOpaqueMaterial` or `MasslessOpaqueMaterial`
creation pattern; repeated construction classes follow the same
`Construction.insertLayer(...)` pattern.

## Core Model Handling

```python
translator = openstudio.openstudioosversion.VersionTranslator()
model_optional = translator.loadModel(osm_path)
model = model_optional.get()
```

`openstudio.openstudioosversion.VersionTranslator()` loads OSM files through the
Python SDK's version translator. The loaded model is an optional object; the
reviewed code often calls `.get()` after a precondition guarantees the model
exists. Safer generated scripts should call `is_initialized()` before `.get()`.

```python
model_optional = openstudio.model.Model.load(str(osm_file_path))
if not model_optional.is_initialized():
    raise ValueError("Failed to load OpenStudio model")
model = model_optional.get()
```

`openstudio.model.Model.load(...)` is another observed way to load a model. It
also returns an optional object that should be checked with `is_initialized()`.

```python
model = openstudio.model.Model()
```

Creates a new empty OpenStudio model.

```python
model.save(str(output_path), True)
model.save(openstudio.toPath(str(output_path)), True)
```

Both save forms appear in the reviewed projects. The second argument overwrites
an existing file when true.

```python
clone_model = model.clone().to_Model()
clone_model.getBuilding().setNorthAxis(90)
```

`clone()` copies a model object, and `to_Model()` casts the clone back to an
OpenStudio model. This is used to create rotated baseline models.

## Optional Objects and Casts

```python
optional_obj = model.getObjectByTypeAndName(
    openstudio.model.Space.iddObjectType(),
    space_name,
)
if optional_obj.empty():
    raise ValueError("Missing object")
space = optional_obj.get().to_Space().get()
```

`getObjectByTypeAndName(...)` returns an optional workspace/model object that is
checked with `.empty()` in the reviewed code. After `.get()`, cast with
`to_Space()`, `to_Construction()`, `to_ScheduleRuleset()`,
`to_StandardOpaqueMaterial()`, etc.; those casts return optionals too.

```python
zone_optional = space.thermalZone()
if zone_optional.is_initialized():
    zone = zone_optional.get()
```

Many typed OpenStudio relationships return optionals checked with
`is_initialized()`, including `thermalZone()`, `defaultScheduleSet()`,
construction-set accessors, and SQL query results.

```python
name = obj.nameString()
name = obj.name().get()
```

Both name access patterns are used. `nameString()` is concise when available.
`name().get()` reflects the optional-name API and assumes the object has a name.

## Python SDK Naming Quirks

```python
len(model.getBuildingStorys())
len(model.getGass())
default_sch_set.setNumberofPeopleSchedule(schedule)
day_sch.setInterpolatetoTimestep("No")
```

The OpenStudio Python API includes historical/non-English-standard method names.
Do not "correct" these to natural English spellings such as
`getBuildingStories()` or `getGases()` unless the SDK confirms those aliases
exist. The reviewed code uses `getBuildingStorys()`, `getGass()`,
`setNumberofPeopleSchedule(...)`, and `setInterpolatetoTimestep(...)`.

## Weather and Design Days

```python
epw_file = openstudio.EpwFile(epw_path)
openstudio.model.WeatherFile.setWeatherFile(model, epw_file)
```

Creates an EPW weather-file object and attaches it to a model.

```python
ddy_file = openstudio.path(ddy_path)
ddy_idf = openstudio.IdfFile.load(ddy_file)
ddy_workspace = openstudio.Workspace(ddy_idf.get())
ddy_model = openstudio.energyplus.ReverseTranslator().translateWorkspace(
    ddy_workspace
)
model.addObjects(ddy_model.objects())
```

Loads a DDY/IDF file, translates it back to an OpenStudio model, and merges the
translated design-day objects into the active model.

## Additional Properties

```python
space.additionalProperties().setFeature("floor_area", floor_area)
space.additionalProperties().setFeature("space_type", "PERIMETER")

value_optional = space.additionalProperties().getFeatureAsDouble("floor_area")
text_optional = space.additionalProperties().getFeatureAsString("space_type")
```

Additional properties are used to carry workflow metadata on model objects, such
as floor area, space depth, building-area key, and orientation. Retrieval returns
optionals; the reviewed utility functions assert `not optional.empty()` before
calling `.get()`.

## Geometry: Spaces, Zones, Surfaces, Subsurfaces

```python
space = openstudio.model.Space(model)
thermal_zone = openstudio.model.ThermalZone(model)
space.setName("Office SPACE")
thermal_zone.setName("Office")
space.setThermalZone(thermal_zone)
```

Creates a space, creates a thermal zone, names both, and assigns the thermal
zone to the space.

```python
points = [openstudio.Point3d(x, y, z) for x, y, z in vertices]
surface = openstudio.model.Surface(points, model)
surface.setSpace(space)
surface.setSurfaceType("Wall")
surface.setOutsideBoundaryCondition("Outdoors")
surface.setSunExposure("SunExposed")
surface.setWindExposure("WindExposure")
```

Creates a surface from four 3D points, assigns it to a space, and sets surface
classification and boundary/exposure metadata.

```python
sub = openstudio.model.SubSurface(points, model)
sub.setName("Perimeter Window")
sub.setSubSurfaceType("FixedWindow")
sub.setSurface(parent_surface)
```

Creates a subsurface, sets its type, and attaches it to a parent surface. The
reviewed projects use `"FixedWindow"`, `"Door"`, and `"GlassDoor"`.

```python
sub.addOverhangByProjectionFactor(projection_factor, 0.0)
```

Adds an overhang to a window or glass door by projection factor. The reviewed
code only does this for proposed-model fenestration when projection factor is
positive.

```python
box = space.boundingBox()
width = box.maxX().get()
depth = box.maxY().get()
height = box.maxZ().get()
```

`boundingBox()` provides geometric extents. Its coordinate accessors return
optionals in the reviewed code, so `.get()` is called after geometry exists.

```python
translation = openstudio.Transformation.translation(openstudio.Vector3d(dx, 0, 0))
translated_vertices = translation * surface.vertices()
surface.setVertices(translated_vertices)
```

Creates a translation transform and applies it to all vertices of a surface.
The same pattern is used for moving subsurfaces along with their parent surface.

```python
matrix = openstudio.Matrix(4, 4, 0)
matrix[0, 0] = scale
matrix[1, 1] = scale
matrix[2, 2] = 1
matrix[3, 3] = 1
matrix[0, 3] = cx * (1 - scale)
matrix[1, 3] = cy * (1 - scale)
transform = openstudio.Transformation(matrix)
scaled_vertices = transform * parent_surface.vertices()
```

Builds a custom 4x4 transform matrix. The reviewed code uses this to scale and
recenter skylight geometry on a roof.

## Constructions and Materials

```python
construction = openstudio.model.Construction(model)
construction.setName("Steel Framed Wall R-13")
construction.insertLayer(0, exterior_material)
construction.insertLayer(1, insulation_material)
```

Creates a construction and inserts material layers in order. Existing
constructions are commonly found with `getObjectByTypeAndName(...)` and cast
with `to_Construction().get()`.

```python
layer = construction.getLayer(0)
layer_count = construction.numLayers()
layers = construction.layers()
```

Retrieves construction layers. Tests in the reviewed projects treat
`getLayer(i)` as a value that may be falsey when not found.

```python
material = openstudio.model.StandardOpaqueMaterial(model)
material.setName("G01 16mm gypsum board")
material.setRoughness("MediumSmooth")
material.setThickness(0.0159)
material.setConductivity(0.16)
material.setDensity(800)
material.setSpecificHeat(1090)
material.setThermalAbsorptance(0.9)
material.setSolarAbsorptance(0.7)
material.setVisibleAbsorptance(0.5)
```

Creates a physical opaque material. The reviewed code uses these setters for
gypsum board, concrete, plywood, metal, roofing, stucco, carpet pad, wood, and
similar layers.

```python
material = openstudio.model.MasslessOpaqueMaterial(model)
material.setThermalResistance(r_si)
material.setThermalAbsorptance(0.9)
material.setSolarAbsorptance(0.7)
material.setVisibleAbsorptance(0.7)
```

Creates a massless material, typically for insulation or dummy air-wall layers.
Thermal resistance passed to OpenStudio is SI. The COMcheck code often receives
IP R-values and converts before setting.

```python
glazing = openstudio.model.SimpleGlazing(model)
glazing.setUFactor(u_si)
glazing.setSolarHeatGainCoefficient(shgc)
glazing.setVisibleTransmittance(vt)
```

Creates a simple glazing material for windows, skylights, or glass doors. The
reviewed COMcheck code converts IP U-factor before calling `setUFactor(...)`.

```python
construction = openstudio.model.FFactorGroundFloorConstruction(model)
construction.setFFactor(f_factor_si)
construction.setArea(area_m2)
construction.setPerimeterExposed(perimeter_m)
```

Creates an F-factor slab-on-grade construction. Area and perimeter are SI in the
reviewed code.

```python
construction = openstudio.model.CFactorUndergroundWallConstruction(
    model,
    c_factor_si,
    depth_m,
)
```

Creates a C-factor underground wall construction. The reviewed code derives
C-factor from U-factor after removing air-film effect, then converts to SI.

## Default Construction Sets

```python
construction_set = openstudio.model.DefaultConstructionSet(model)
exterior = openstudio.model.DefaultSurfaceConstructions(model)
subsurface = openstudio.model.DefaultSubSurfaceConstructions(model)

construction_set.setDefaultExteriorSurfaceConstructions(exterior)
exterior.setWallConstruction(wall_construction)
exterior.setRoofCeilingConstruction(roof_construction)
exterior.setFloorConstruction(floor_construction)

construction_set.setDefaultExteriorSubSurfaceConstructions(subsurface)
subsurface.setFixedWindowConstruction(window_construction)
subsurface.setDoorConstruction(door_construction)
subsurface.setSkylightConstruction(skylight_construction)

model.getBuilding().setDefaultConstructionSet(construction_set)
```

Creates and applies default construction sets. This pattern is central in
the reviewed typical-building source.

```python
default_cs_opt = model.getBuilding().defaultConstructionSet()
if default_cs_opt.is_initialized():
    default_cs = default_cs_opt.get()
```

Retrieves the model building's assigned default construction set. Nested
construction-set accessors also return optionals.

## Schedules and Space Types

```python
ruleset = openstudio.model.ScheduleRuleset(model)
default_day = ruleset.defaultDaySchedule()
default_day.addValue(openstudio.Time(0, 24, 0, 0), 0.5)
```

Creates a schedule ruleset and sets a constant all-day value on the default day.

```python
day = openstudio.model.ScheduleDay(model)
day.setName("Weekday")
day.setInterpolatetoTimestep("No")
for hour, value in enumerate(values, start=1):
    day.addValue(openstudio.Time(0, hour, 0, 0), value)
```

Creates an hourly day schedule. The reviewed implementation skips consecutive
duplicate values to reduce schedule rows.

```python
rule = openstudio.model.ScheduleRule(ruleset)
rule_day = rule.daySchedule()
rule_day.addValue(openstudio.Time(0, 18, 0, 0), 1.0)
rule.setApplyMonday(True)
rule.setApplyTuesday(True)
rule.setStartDate(openstudio.Date(openstudio.MonthOfYear(1), 1))
rule.setEndDate(openstudio.Date(openstudio.MonthOfYear(12), 31))
```

Creates a schedule rule, edits the rule's day schedule, applies it to days of
the week, and sets a date range.

```python
default_set_opt = space_type.defaultScheduleSet()
if default_set_opt.is_initialized():
    default_set = default_set_opt.get()
else:
    default_set = openstudio.model.DefaultScheduleSet(model)
    space_type.setDefaultScheduleSet(default_set)

default_set.setNumberofPeopleSchedule(occ_schedule)
default_set.setPeopleActivityLevelSchedule(activity_schedule)
default_set.setLightingSchedule(light_schedule)
default_set.setElectricEquipmentSchedule(equip_schedule)
default_set.setGasEquipmentSchedule(gas_schedule)
```

Ensures a `SpaceType` has a default schedule set and assigns internal load
schedules.

```python
space_type.setStandardsBuildingType("Office")
space_type.setStandardsSpaceType("WholeBuilding - Sm Office")

bldg_opt = space_type.standardsBuildingType()
space_opt = space_type.standardsSpaceType()
```

Stores and retrieves standards tags on `SpaceType` objects. The getters return
optionals and are used for automatic schedule application.

## HVAC and Controls

```python
air_loop = openstudio.model.AirLoopHVAC(model)
air_loop.setNightCycleControlType("CycleOnAny")
```

Creates a single-zone air loop and sets night cycling.

```python
controller_oa = openstudio.model.ControllerOutdoorAir(model)
controller_oa.setMinimumOutdoorAirSchedule(hvac_schedule)
controller_oa.setEconomizerControlType("FixedDryBulb")
controller_oa.setEconomizerMaximumLimitDryBulbTemperature(max_temp_c)
controller_oa.setLockoutType("LockoutWithHeating")

oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller_oa)
oa_system.addToNode(air_loop.supplyOutletNode())
```

Creates an outdoor air controller and adds an outdoor air system to the air
loop's supply outlet node.

```python
terminal = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
    model,
    model.alwaysOnDiscreteSchedule(),
)
air_loop.addBranchForZone(thermal_zone, terminal)
```

Adds a constant-volume no-reheat terminal and connects the air loop to a thermal
zone.

```python
cooling_coil = openstudio.model.CoilCoolingDXSingleSpeed(
    model,
    availability_schedule,
    cap_ft_curve,
    cap_flow_curve,
    eir_temp_curve,
    eir_flow_curve,
    plf_curve,
)
cooling_coil.autosizeRatedTotalCoolingCapacity()
cooling_coil.setRatedCOP(4.4)
```

Creates a single-speed DX cooling coil with performance curves, autosizes
capacity, and sets rated COP.

```python
heating_coil = openstudio.model.CoilHeatingGas(model, availability_schedule)
heating_coil.autosizeNominalCapacity()
heating_coil.setGasBurnerEfficiency(0.8)
```

Creates a gas heating coil, autosizes nominal capacity, and sets gas burner
efficiency.

```python
fan = openstudio.model.FanConstantVolume(model, hvac_schedule)
fan.autosizeMaximumFlowRate()
fan.setFanEfficiency(0.65)
fan.setMotorEfficiency(0.90)
fan.setPressureRise(373.6)
```

Creates a constant-volume fan and sets autosizing and fan performance fields.

```python
fan_inlet = fan.inletModelObject().get().to_Node().get()
fan_outlet = fan.outletModelObject().get().to_Node().get()
coil_outlet = cooling_coil.outletModelObject().get().to_Node().get()
```

Gets HVAC component inlet/outlet model objects and casts them to nodes. These
calls assume the components are already connected enough for the optional values
to exist.

```python
spm = openstudio.model.SetpointManagerMixedAir(model)
spm.setFanInletNode(fan_inlet)
spm.setFanOutletNode(fan_outlet)
spm.setReferenceSetpointNode(fan_outlet)
spm.setControlVariable("Temperature")
spm.addToNode(coil_outlet)
```

Creates and attaches a mixed-air setpoint manager.

```python
spm = openstudio.model.SetpointManagerSingleZoneReheat(model)
spm.setControlZone(thermal_zone)
spm.setMaximumSupplyAirTemperature(99)
spm.setMinimumSupplyAirTemperature(-99)
spm.addToNode(air_loop.supplyOutletNode())
```

Creates and attaches a single-zone reheat setpoint manager.

```python
thermostat = openstudio.model.ThermostatSetpointDualSetpoint(model)
thermostat.setCoolingSetpointTemperatureSchedule(cooling_schedule)
thermostat.setHeatingSetpointTemperatureSchedule(heating_schedule)
thermal_zone.setThermostatSetpointDualSetpoint(thermostat)
```

Creates a dual setpoint thermostat and assigns it to a thermal zone.

## Daylighting Controls

```python
control = openstudio.model.DaylightingControl(model)
control.setSpace(space)
control.setPosition(openstudio.Point3d(x, y, z))
control.setIlluminanceSetpoint(538.195520835486)
control.setLightingControlType("Continuous")
control.setMinimumInputPowerFractionforContinuousDimmingControl(0.2)
control.setMinimumLightOutputFractionforContinuousDimmingControl(0.06)
```

Creates a daylighting control at a point in a space and configures continuous
dimming behavior.

```python
thermal_zone.setPrimaryDaylightingControl(control)
thermal_zone.setFractionofZoneControlledbyPrimaryDaylightingControl(fraction)
thermal_zone.setSecondaryDaylightingControl(existing_control)
thermal_zone.setFractionofZoneControlledbySecondaryDaylightingControl(fraction)
```

Assigns primary/secondary daylighting controls to a thermal zone. The reviewed
code recalibrates primary plus secondary fractions so their sum does not exceed
1.0.

## Infiltration

```python
infiltration = openstudio.model.SpaceInfiltrationDesignFlowRate(model)
infiltration.setName(f"{space_name}_Infiltration")
infiltration.setSpace(space)
infiltration.setFlowperExteriorWallArea(flow_per_wall_area)
infiltration.setConstantTermCoefficient(0)
infiltration.setTemperatureTermCoefficient(0)
infiltration.setVelocitySquaredTermCoefficient(0)
infiltration.setVelocityTermCoefficient(0.224)
```

Creates a space infiltration object, assigns it to a space, and sets prototype
style coefficients.

## Unit Conversion

```python
cooling_temp_c = openstudio.convert(55, "F", "C").get()
area_ft2 = openstudio.convert(area_m2, "m^2", "ft^2").get()
azimuth_deg = openstudio.convert(surface.azimuth(), "rad", "deg").get()
```

`openstudio.convert(...)` returns an optional numeric conversion result. Check
`is_initialized()` before `.get()` in generated scripts when inputs may be
invalid. `surface.azimuth()` is radians in the Python SDK usage expected by
OpenStudio AI, so convert to degrees before cardinal binning.

## Simulation Workflow

```python
forward_translator = openstudio.energyplus.ForwardTranslator()
idf = forward_translator.translateModel(model)
idf.save(openstudio.path(f"{run_dir}/in.idf"), True)
model.save(openstudio.path(f"{run_dir}/in.osm"), True)
```

Translates an OpenStudio model to EnergyPlus IDF and saves both IDF and OSM run
inputs.

```python
model.resetSqlFile()
workflow = openstudio.WorkflowJSON()
workflow.setSeedFile("in.osm")
workflow.setWeatherFile(epw_name)
workflow.saveAs(os.path.abspath(str(osw_path)))
```

Prepares an OSW workflow for command-line simulation. `resetSqlFile()` detaches
any previous SQL result from the model before running.

```python
sql_path = openstudio.path(os.path.join(run_dir, "run", "eplusout.sql"))
if openstudio.exists(sql_path):
    sql = openstudio.SqlFile(sql_path)
    if sql.connectionOpen():
        model.setSqlFile(sql)
```

Checks for EnergyPlus SQL output, verifies it can be opened, and attaches it to
the model.

```python
errs_optional = model.sqlFile().get().execAndReturnVectorOfString(
    "SELECT ErrorMessage FROM Errors WHERE ErrorType in(1,2)"
)
if errs_optional.is_initialized():
    errs = errs_optional.get()
```

Runs a direct SQL query through the attached OpenStudio SQL file and checks the
optional vector result.

## SQL Result Extraction

```python
sql = openstudio.SqlFile(openstudio.path(ep_sql_file_path))
gas_gj = sql.naturalGasTotalEndUses().get()
electricity_gj = sql.electricityTotalEndUses().get()
```

Loads an EnergyPlus SQL file and retrieves total natural gas and electricity end
uses. These return optionals in the reviewed code and are immediately unwrapped
after the SQL file exists.

## Output Summary Reports

```python
reports = model.getOutputTableSummaryReports()
reports.addSummaryReport("AllSummaryAndSizingPeriod")
```

Adds standard summary reports to the model output requests.

## Practical Agent Drafting Rules Learned

- Use a version-translator compatibility helper when drafting robust OSM load
  examples for OpenStudio AI; some bindings expose
  `openstudio.openstudioosversion.VersionTranslator()` and others expose
  `openstudio.osversion.VersionTranslator()`.
- Treat `is_initialized()` and `.empty()` as distinct optional checks. Typed
  model relationships commonly use `is_initialized()`;
  `getObjectByTypeAndName(...)` results in these projects use `.empty()`.
- Keep OpenStudio's historical method spellings exactly as observed:
  `getBuildingStorys()`, `getGass()`, `setNumberofPeopleSchedule(...)`,
  `setInterpolatetoTimestep(...)`.
- Convert units explicitly before setting fields when the source value is in IP.
  OpenStudio setters commonly expect SI values.
- Create geometry with four `openstudio.Point3d` vertices for rectangular
  surfaces/subsurfaces, then attach surfaces to spaces and subsurfaces to parent
  surfaces.
- For edits that may change simulation outcomes, save to a copied output model
  path instead of overwriting the input model.
- For repeated object creation, first search by object type and name, then reuse
  the existing object when present.

## Items Needing Human Confirmation Before Generalizing

- Some reviewed COMcheck code calls `.get()` directly after project-specific
  preconditions. Generated scripts should use explicit checks unless the user
  confirms the same precondition.
- The reviewed projects mix `model.save(str(path), True)`,
  `model.save(openstudio.path(...), True)`, and
  `model.save(openstudio.toPath(...), True)`. All are source-observed, but use
  one consistent style in generated scripts unless a project requires another.
- The exact accepted strings for surface types, boundary conditions, exposure
  fields, schedule day types, and HVAC control types should be copied from
  source examples or checked against the SDK before inventing new values.
