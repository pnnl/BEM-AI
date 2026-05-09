---
name: sdk_spaces_zones_loads
description: OpenStudio Python SDK examples for spaces, thermal zones, and internal loads.
version: 0.1.0
source_domains:
  - openstudio-standards/space/space.rb
  - openstudio-standards/thermal_zone/thermal_zone.rb
  - openstudio-standards/qaqc/internal_loads.rb
---

# SDK Spaces, Zones, and Loads Context

Use this pack for space/zone inspection, plenum classification,
heated/cooled classification, area summaries, internal load summaries, and
outdoor air summaries.

## Space and Zone Summary

```python
rows = []
for space in model.getSpaces():
    zone_opt = space.thermalZone()
    space_type_opt = space.spaceType()
    rows.append({
        "space": space.nameString(),
        "thermal_zone": zone_opt.get().nameString() if zone_opt.is_initialized() else None,
        "space_type": space_type_opt.get().nameString() if space_type_opt.is_initialized() else None,
        "floor_area_m2": space.floorArea(),
        "volume_m3": space.volume(),
        "part_of_total_floor_area": space.partofTotalFloorArea(),
        "multiplier": space.multiplier(),
    })
counts["spaces"] = len(rows)
counts["thermal_zones"] = len(model.getThermalZones())
```

## Plenum Heuristic

```python
def is_plenum_space(space):
    if not space.partofTotalFloorArea():
        return True
    space_type_opt = space.spaceType()
    if space_type_opt.is_initialized():
        space_type = space_type_opt.get()
        names = [space_type.nameString()]
        if space_type.standardsSpaceType().is_initialized():
            names.append(space_type.standardsSpaceType().get())
        return any("plenum" in name.lower() for name in names)
    return False

plenum_spaces = [space.nameString() for space in model.getSpaces() if is_plenum_space(space)]
```

## Thermal Zone Plenum Majority

```python
def is_plenum_zone(zone):
    plenum_area = 0.0
    non_plenum_area = 0.0
    for space in zone.spaces():
        if is_plenum_space(space):
            plenum_area += space.floorArea()
        else:
            non_plenum_area += space.floorArea()
    return plenum_area > non_plenum_area
```

## Design Internal Load by Space

This estimates design internal heat gain from people, lights, electric
equipment, and gas equipment. It is for model inspection, not a simulation
result.

```python
load_rows = []
for space in model.getSpaces():
    people_w = 0.0
    for people in space.people():
        number_people = people.getNumberOfPeople(space.floorArea())
        w_per_person = 125.0
        activity_opt = people.activityLevelSchedule()
        if activity_opt.is_initialized():
            ruleset_opt = activity_opt.get().to_ScheduleRuleset()
            if ruleset_opt.is_initialized():
                values = list(ruleset_opt.get().defaultDaySchedule().values())
                if values:
                    w_per_person = max(values)
        people_w += number_people * w_per_person

    row = {
        "space": space.nameString(),
        "people_w": people_w,
        "lighting_w": space.lightingPower(),
        "electric_equipment_w": space.electricEquipmentPower(),
        "gas_equipment_w": space.gasEquipmentPower(),
    }
    row["total_internal_load_w"] = (
        row["people_w"]
        + row["lighting_w"]
        + row["electric_equipment_w"]
        + row["gas_equipment_w"]
    )
    load_rows.append(row)
```

## Outdoor Air by Zone

```python
oa_rows = []
for zone in model.getThermalZones():
    total_oa_m3_s = 0.0
    for space in zone.spaces():
        dsoa_opt = space.designSpecificationOutdoorAir()
        if not dsoa_opt.is_initialized():
            continue
        dsoa = dsoa_opt.get()
        total_oa_m3_s += dsoa.outdoorAirFlowRate()
        total_oa_m3_s += dsoa.outdoorAirFlowperFloorArea() * space.floorArea()
        people_count = sum(p.getNumberOfPeople(space.floorArea()) for p in space.people())
        total_oa_m3_s += dsoa.outdoorAirFlowperPerson() * people_count
        total_oa_m3_s += dsoa.outdoorAirFlowAirChangesperHour() * space.volume() / 3600.0
    oa_rows.append({
        "thermal_zone": zone.nameString(),
        "outdoor_air_m3_s": total_oa_m3_s,
    })
```

## Find Zones by Name

```python
target_names = {"Perimeter_ZN_1", "Core_ZN"}
target_names_lower = {name.lower() for name in target_names}
target_zones = [
    zone for zone in model.getThermalZones()
    if zone.nameString().strip().lower() in target_names_lower
]
if len(target_zones) != len(target_names):
    found_lower = {zone.nameString().strip().lower() for zone in target_zones}
    missing = [name for name in target_names if name.lower() not in found_lower]
    warnings.append(f"Requested zones not found: {sorted(missing)}")
```
