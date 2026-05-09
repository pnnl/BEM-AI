---
name: sdk_constructions
description: OpenStudio Python SDK examples for construction and material inspection/editing.
version: 0.1.0
source_domains:
  - openstudio-standards/constructions/information.rb
  - openstudio-standards/constructions/modify.rb
  - openstudio-standards/constructions/materials/modify.rb
---

# SDK Constructions Context

Use this pack for construction layers, insulation layers, thermal resistance,
opaque material edits, opaque U-value edits, and simple glazing U-factor edits.

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
