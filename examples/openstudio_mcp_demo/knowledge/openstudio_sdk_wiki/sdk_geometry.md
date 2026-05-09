---
name: sdk_geometry
description: OpenStudio Python SDK examples for geometry inspection and scoped geometry edits.
version: 0.1.0
source_domains:
  - openstudio-standards/geometry/information.rb
  - openstudio-standards/geometry/modify.rb
---

# SDK Geometry Context

Use this pack for surfaces, subsurfaces, WWR, orientation, exterior areas,
building stories, north axis, and window area edits.

## Azimuth Unit Rule

`surface.azimuth()` returns radians. Do not treat it as degrees and do not use
manual `math.pi` conversion. Convert with OpenStudio's unit conversion helper
and check the optional before using the value:

```python
def surface_azimuth_degrees(surface):
    azimuth_opt = openstudio.convert(surface.azimuth(), "rad", "deg")
    if not azimuth_opt.is_initialized():
        raise ValueError(f"Could not convert azimuth for {surface.nameString()}.")
    return azimuth_opt.get()
```

## Building Story Getter Rule

OpenStudio's Python SDK uses the historical plural spelling
`model.getBuildingStorys()` for building-story collection access.

```python
story_rows = []
for story in model.getBuildingStorys():
    spaces = list(story.spaces())
    story_rows.append({
        "name": story.nameString(),
        "space_count": len(spaces),
        "space_names": [space.nameString() for space in spaces],
        "floor_area_m2": sum(space.floorArea() for space in spaces),
    })
```

## Inspect Exterior WWR by Orientation

```python
orientation_bins = {"N": [], "E": [], "S": [], "W": []}

def cardinal_direction(azimuth_deg):
    azimuth_deg = azimuth_deg % 360.0
    if azimuth_deg <= 45.0 or azimuth_deg > 315.0:
        return "N"
    if azimuth_deg <= 135.0:
        return "E"
    if azimuth_deg <= 225.0:
        return "S"
    return "W"

building_north = model.getBuilding().northAxis()
for surface in model.getSurfaces():
    if surface.surfaceType() != "Wall":
        continue
    if surface.outsideBoundaryCondition() != "Outdoors":
        continue
    wall_area = surface.grossArea()
    window_area = sum(
        ss.netArea()
        for ss in surface.subSurfaces()
        if ss.subSurfaceType() in {"FixedWindow", "OperableWindow", "GlassDoor"}
    )
    space_opt = surface.space()
    space_north = space_opt.get().directionofRelativeNorth() if space_opt.is_initialized() else 0.0
    azimuth_deg = surface_azimuth_degrees(surface)
    direction = cardinal_direction(azimuth_deg + space_north + building_north)
    orientation_bins[direction].append({"wall_area_m2": wall_area, "window_area_m2": window_area})

wwr_by_orientation = {}
for direction, rows in orientation_bins.items():
    wall_area = sum(row["wall_area_m2"] for row in rows)
    window_area = sum(row["window_area_m2"] for row in rows)
    wwr_by_orientation[direction] = window_area / wall_area if wall_area else 0.0
```

## Reduce Window Area by Shrinking Toward Centroid

This pattern preserves the subsurface plane and scales each vertex toward the
centroid. A `percent_reduction` of `0.2` reduces area by roughly 20 percent.

```python
percent_reduction = 0.2
scale_factor = (1.0 - percent_reduction) ** 0.5

for sub_surface in target_subsurfaces:
    before_area = sub_surface.netArea()
    centroid = sub_surface.centroid()
    new_vertices = []
    for vertex in sub_surface.vertices():
        vector = vertex - centroid
        vector.setLength(vector.length() * scale_factor)
        new_vertices.append(centroid + vector)
    sub_surface.setVertices(new_vertices)
    changes.append({
        "object": sub_surface.nameString(),
        "field": "vertices",
        "before_area_m2": before_area,
        "after_area_m2": sub_surface.netArea(),
    })
```

## Reduce Window Area by Raising Sill

Use this only for vertical rectangular windows where raising the lower vertices
is the intended edit.

```python
percent_reduction = 0.2
tolerance_m = 0.025

for sub_surface in target_subsurfaces:
    vertices = list(sub_surface.vertices())
    min_z = min(vertex.z() for vertex in vertices)
    max_z = max(vertex.z() for vertex in vertices)
    z_delta = (max_z - min_z) * percent_reduction
    before_area = sub_surface.netArea()
    new_vertices = []
    for vertex in vertices:
        if abs(vertex.z() - min_z) < tolerance_m:
            new_vertices.append(vertex + openstudio.Vector3d(0.0, 0.0, z_delta))
        else:
            new_vertices.append(vertex)
    sub_surface.setVertices(new_vertices)
    changes.append({
        "object": sub_surface.nameString(),
        "field": "sill_height",
        "before_area_m2": before_area,
        "after_area_m2": sub_surface.netArea(),
    })
```

## Rename Surfaces and Subsurfaces

```python
for space in model.getSpaces():
    surface_type_counter = {}
    for surface in sorted(space.surfaces(), key=lambda item: item.nameString()):
        surface_type = surface.surfaceType()
        surface_type_counter[surface_type] = surface_type_counter.get(surface_type, 0) + 1
        surface.setName(f"{space.nameString()} {surface_type} {surface_type_counter[surface_type]}")

        sub_type_counter = {}
        for sub_surface in sorted(surface.subSurfaces(), key=lambda item: item.nameString()):
            sub_type = sub_surface.subSurfaceType()
            sub_type_counter[sub_type] = sub_type_counter.get(sub_type, 0) + 1
            sub_surface.setName(f"{surface.nameString()} {sub_type} {sub_type_counter[sub_type]}")
```

## Set Building North Axis

```python
north_axis_deg = 15.0
building = model.getBuilding()
old = building.northAxis()
building.setNorthAxis(north_axis_deg)
changes.append({
    "object": building.nameString(),
    "field": "northAxis",
    "before": old,
    "after": north_axis_deg,
    "units": "degrees",
})
```
