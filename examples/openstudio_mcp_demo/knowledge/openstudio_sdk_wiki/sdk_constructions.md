---
name: sdk_constructions
description: OpenStudio Python SDK examples for construction and material inspection/editing.
version: 0.1.0
---

# SDK Constructions Context

Use this pack for construction layers, insulation layers, thermal resistance,
opaque material edits, opaque U-value edits, and simple glazing U-factor edits.

For any construction or material creation request, apply the global object
creation rule from `sdk_core_patterns`: identify the required names, numeric
values, units, target constructions/surfaces, and referenced material objects;
ask the user for missing inputs; convert IP values to SI before SDK setters; and
list approved default assumptions with `Object:Name.parameter: assumed to be x`.

## Inspect Layers and Material Properties

```python
def material_row(material):
    row = {
        "name": material.nameString(),
        "type": type(material).__name__,
        "thermal_resistance_m2k_w": None,
        "thickness_m": None,
        "conductivity_w_mk": None,
        "density_kg_m3": None,
        "specific_heat_j_kgk": None,
    }
    if hasattr(material, "thermalResistance"):
        row["thermal_resistance_m2k_w"] = material.thermalResistance()
    if hasattr(material, "thickness"):
        row["thickness_m"] = material.thickness()
    if hasattr(material, "conductivity"):
        row["conductivity_w_mk"] = material.conductivity()
    if hasattr(material, "density"):
        row["density_kg_m3"] = material.density()
    if hasattr(material, "specificHeat"):
        row["specific_heat_j_kgk"] = material.specificHeat()
    return row

construction_rows = []
for construction in model.getConstructions():
    layer_rows = []
    for layer in construction.layers():
        layer_rows.append(material_row(layer))
    construction_rows.append({
        "construction": construction.nameString(),
        "num_layers": construction.numLayers(),
        "layers": layer_rows,
    })
```

`material.thermalResistance()` is used by massless materials and retrieves the
material resistance value in SI units when available; source examples treat
missing or falsey resistance as possible. Standard opaque materials typically
expose `thickness()`, `conductivity()`, `density()`, and `specificHeat()`
instead.

## Inspect Exterior Surface Constructions

```python
rows = []
for surface in model.getSurfaces():
    if surface.outsideBoundaryCondition() != "Outdoors":
        continue
    construction_opt = surface.construction()
    rows.append({
        "surface": surface.nameString(),
        "surface_type": surface.surfaceType(),
        "area_m2": surface.netArea(),
        "construction": (
            construction_opt.get().nameString()
            if construction_opt.is_initialized()
            else None
        ),
    })
```

## Find Likely Insulation Layer

```python
def opaque_conductance(material):
    if hasattr(material, "thermalResistance"):
        resistance = material.thermalResistance()
        return 1.0 / resistance if resistance else None
    if hasattr(material, "conductivity") and hasattr(material, "thickness"):
        thickness = material.thickness()
        return material.conductivity() / thickness if thickness else None
    return None

def find_likely_insulation_layer(construction):
    layered_opt = construction.to_LayeredConstruction()
    if not layered_opt.is_initialized():
        return None
    best_layer = None
    best_conductance = None
    for layer in layered_opt.get().layers():
        opaque_opt = layer.to_OpaqueMaterial()
        if not opaque_opt.is_initialized():
            continue
        material = opaque_opt.get()
        conductance = opaque_conductance(material)
        if conductance is None:
            continue
        if best_conductance is None or conductance < best_conductance:
            best_layer = material
            best_conductance = conductance
    return best_layer
```

## Add Opaque Material Layer

Before using this creation pattern, ask for the material name, roughness,
thickness, conductivity, density, specific heat, thermal absorptance, solar
absorptance, visible absorptance, target construction, and insertion layer
index if any are missing. `setThickness`, `setConductivity`, `setDensity`, and
`setSpecificHeat` expect SI values.

```python
construction = target_construction
new_material = openstudio.model.StandardOpaqueMaterial(model)
new_material.setName(f"{construction.nameString()} Added Insulation")
new_material.setRoughness("MediumRough")
new_material.setThickness(0.05)
new_material.setConductivity(0.04)
new_material.setDensity(32.0)
new_material.setSpecificHeat(840.0)
new_material.setThermalAbsorptance(0.9)
new_material.setSolarAbsorptance(0.7)
new_material.setVisibleAbsorptance(0.7)
construction.insertLayer(0, new_material)
changes.append({
    "object": construction.nameString(),
    "field": "layers",
    "after": f"Inserted {new_material.nameString()} at layer 0",
})
```

## Create Massless Insulation Material

Before using this creation pattern, ask for material name, roughness, thermal
resistance value and unit system, thermal absorptance, solar absorptance, and
visible absorptance if any are missing. `setThermalResistance` expects SI
`m^2*K/W`; convert IP `ft^2*h*R/Btu` first.

```python
material = openstudio.model.MasslessOpaqueMaterial(model)
material.setName("Added Massless Insulation")
material.setRoughness("MediumSmooth")
material.setThermalResistance(r_si)
material.setThermalAbsorptance(0.9)
material.setSolarAbsorptance(0.7)
material.setVisibleAbsorptance(0.7)
```

Use massless opaque material when the target is an R-value layer rather than a
physical thickness/conductivity material.

## Create F-Factor Slab Construction

Before using this creation pattern, ask for the construction name, F-factor
value and unit system, area value and unit system, and exposed perimeter value
and unit system. OpenStudio setters expect SI values: F-factor in `W/m*K`, area
in `m^2`, and exposed perimeter in `m`. If the user provides IP values, convert
them before calling the setters.

```python
construction = openstudio.model.FFactorGroundFloorConstruction(model)
construction.setName("Unheated Slab F-Factor")
construction.setFFactor(f_factor_si)
construction.setArea(area_m2)
construction.setPerimeterExposed(perimeter_m)
```

This pattern creates a slab-on-grade construction using F-factor, area, and
exposed perimeter in SI units.

## Create C-Factor Underground Wall Construction

Before using this creation pattern, ask for the construction name, C-factor
value and unit system, and wall depth value and unit system. OpenStudio expects
SI values for the constructor. If the user provides IP values, convert them
before creating the construction.

```python
construction = openstudio.model.CFactorUndergroundWallConstruction(
    model,
    c_factor_si,
    depth_m,
)
construction.setName("Below Grade Wall C-Factor")
```

This pattern creates a below-grade wall construction using C-factor and wall
depth in SI units.

## Apply Default Construction Set

Before using this creation pattern, ask for the construction set name and which
existing construction objects should be assigned to each default slot. Retrieve
candidate constructions from the model and ask the user to choose when the
target wall, roof, floor, window, door, or skylight construction is ambiguous.

```python
construction_set = openstudio.model.DefaultConstructionSet(model)
construction_set.setName("ASHRAE Default Construction Set")

exterior = openstudio.model.DefaultSurfaceConstructions(model)
construction_set.setDefaultExteriorSurfaceConstructions(exterior)
exterior.setWallConstruction(wall_construction)
exterior.setRoofCeilingConstruction(roof_construction)
exterior.setFloorConstruction(floor_construction)

subsurface = openstudio.model.DefaultSubSurfaceConstructions(model)
construction_set.setDefaultExteriorSubSurfaceConstructions(subsurface)
subsurface.setFixedWindowConstruction(window_construction)
subsurface.setDoorConstruction(door_construction)
subsurface.setSkylightConstruction(skylight_construction)

model.getBuilding().setDefaultConstructionSet(construction_set)
```

Use construction-set objects when assigning default envelope constructions at
the building level instead of editing each surface one by one.

## Set Opaque Insulation R-Value

This pattern edits the likely insulation layer only. Confirm the target
construction and units with the user before execution.

```python
target_r_ip = 20.0
target_r_si = openstudio.convert(target_r_ip, "ft^2*h*R/Btu", "m^2*K/W").get()
layer = find_likely_insulation_layer(target_construction)
if layer is None:
    warnings.append(f"No likely insulation layer found for {target_construction.nameString()}.")
else:
    before = {"name": layer.nameString()}
    standard_opt = layer.to_StandardOpaqueMaterial()
    massless_opt = layer.to_MasslessOpaqueMaterial()
    if standard_opt.is_initialized():
        material = standard_opt.get()
        before["thickness_m"] = material.thickness()
        material.setThickness(target_r_si * material.conductivity())
        after = {"thickness_m": material.thickness()}
    elif massless_opt.is_initialized():
        material = massless_opt.get()
        before["thermal_resistance_m2k_w"] = material.thermalResistance()
        material.setThermalResistance(target_r_si)
        after = {"thermal_resistance_m2k_w": material.thermalResistance()}
    else:
        warnings.append(f"Insulation layer {layer.nameString()} is not editable by this recipe.")
        after = None

    if after is not None:
        changes.append({
            "object": target_construction.nameString(),
            "field": "insulation_r_value",
            "before": before,
            "after": after,
            "target_r_ip": target_r_ip,
        })
```

## Set Simple Glazing U-Factor

```python
target_u_ip = 0.45
target_u_si = openstudio.convert(target_u_ip, "Btu/ft^2*hr*R", "W/m^2*K").get()
layered_opt = target_construction.to_LayeredConstruction()
if not layered_opt.is_initialized():
    warnings.append(f"{target_construction.nameString()} is not layered.")
else:
    layers = list(layered_opt.get().layers())
    glazing_opt = layers[0].to_SimpleGlazing() if layers else None
    if glazing_opt is None or not glazing_opt.is_initialized():
        warnings.append(f"{target_construction.nameString()} does not use SimpleGlazing.")
    else:
        glazing = glazing_opt.get()
        before = glazing.uFactor()
        glazing.setUFactor(target_u_si)
        changes.append({
            "object": target_construction.nameString(),
            "field": "simple_glazing_u_factor",
            "before_w_m2k": before,
            "after_w_m2k": glazing.uFactor(),
            "target_u_ip": target_u_ip,
        })
```
