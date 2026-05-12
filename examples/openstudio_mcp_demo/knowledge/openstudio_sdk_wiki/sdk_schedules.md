---
name: sdk_schedules
description: OpenStudio Python SDK examples for creating and editing schedules.
version: 0.1.0
---

# SDK Schedules Context

Use this pack for schedule type limits, constant schedules, day schedules,
ruleset schedules, hourly profile edits, and schedule multipliers.

For any schedule creation request, apply the global object creation rule from
`sdk_core_patterns`: ask for missing schedule names, type limits, values, units,
date ranges, days of week, and target space types or model objects before
execution. If the user requests defaults, list them with
`Object:Name.parameter: assumed to be x`.

## Create Schedule Type Limits

```python
def get_or_create_fraction_limits(model):
    existing = model.getScheduleTypeLimitsByName("Fraction")
    if existing.is_initialized():
        return existing.get()
    limits = openstudio.model.ScheduleTypeLimits(model)
    limits.setName("Fraction")
    limits.setLowerLimitValue(0.0)
    limits.setUpperLimitValue(1.0)
    limits.setNumericType("Continuous")
    limits.setUnitType("Dimensionless")
    return limits
```

## Create a Constant Ruleset Schedule

```python
def create_constant_schedule(model, name, value, schedule_type_limits=None):
    existing = model.getScheduleRulesetByName(name)
    if existing.is_initialized():
        existing_schedule = existing.get()
        values = list(existing_schedule.defaultDaySchedule().values())
        if len(values) == 1 and abs(values[0] - value) < 1.0e-6:
            return existing_schedule

    schedule = openstudio.model.ScheduleRuleset(model)
    schedule.setName(name)
    default_day = schedule.defaultDaySchedule()
    default_day.setName(f"{name} Default")
    default_day.addValue(openstudio.Time(0, 24, 0, 0), value)
    if schedule_type_limits is not None:
        schedule.setScheduleTypeLimits(schedule_type_limits)
    return schedule
```

## Populate a Day Schedule from 24 Values

```python
def populate_day_schedule(schedule_day, hourly_values):
    if len(hourly_values) != 24:
        raise ValueError("hourly_values must contain exactly 24 values.")
    schedule_day.setInterpolatetoTimestep("No")
    schedule_day.clearValues()
    for hour, value in enumerate(hourly_values):
        next_value = hourly_values[hour + 1] if hour < 23 else None
        if value == next_value:
            continue
        schedule_day.addValue(openstudio.Time(0, hour + 1, 0, 0), value)
    return schedule_day
```

`setInterpolatetoTimestep` is the observed Python SDK spelling. Do not rewrite
it to `setInterpolateToTimestep`.

## Add a Ruleset Rule from Hourly Values

```python
rule = openstudio.model.ScheduleRule(schedule_ruleset)
day_schedule = rule.daySchedule()
day_schedule.setName("Weekday Profile")
populate_day_schedule(day_schedule, weekday_values)

for setter in (
    rule.setApplyMonday,
    rule.setApplyTuesday,
    rule.setApplyWednesday,
    rule.setApplyThursday,
    rule.setApplyFriday,
):
    setter(True)

rule.setStartDate(openstudio.Date(openstudio.MonthOfYear(1), 1))
rule.setEndDate(openstudio.Date(openstudio.MonthOfYear(12), 31))
```

`openstudio.Date(openstudio.MonthOfYear(month), day)` is the observed pattern
for schedule rule date ranges.

## Default Schedule Set on SpaceType

```python
default_set_opt = space_type.defaultScheduleSet()
if default_set_opt.is_initialized():
    default_set = default_set_opt.get()
else:
    default_set = openstudio.model.DefaultScheduleSet(model)
    default_set.setName(f"{space_type.nameString()} Schedule Set")
    space_type.setDefaultScheduleSet(default_set)

default_set.setNumberofPeopleSchedule(occupancy_schedule)
default_set.setPeopleActivityLevelSchedule(activity_schedule)
default_set.setLightingSchedule(lighting_schedule)
default_set.setElectricEquipmentSchedule(equipment_schedule)
default_set.setGasEquipmentSchedule(gas_schedule)
```

Use `DefaultScheduleSet` when assigning people, activity, lighting, electric
equipment, and gas equipment schedules to a `SpaceType`. The observed method
name is `setNumberofPeopleSchedule`.

## Standards Tags on SpaceType

```python
space_type.setStandardsBuildingType("Office")
space_type.setStandardsSpaceType("WholeBuilding - Sm Office")

bldg_opt = space_type.standardsBuildingType()
space_opt = space_type.standardsSpaceType()
if bldg_opt.is_initialized() and space_opt.is_initialized():
    tag = f"{bldg_opt.get()} - {space_opt.get()}"
```

Standards tags are useful for automatically applying schedules by space-type
metadata. The getters return optionals.

## Multiply Ruleset Values with Bounds

```python
def bounds_from_schedule(schedule_ruleset):
    lower = float("-inf")
    upper = float("inf")
    limits_opt = schedule_ruleset.scheduleTypeLimits()
    if limits_opt.is_initialized():
        limits = limits_opt.get()
        if limits.lowerLimitValue().is_initialized():
            lower = limits.lowerLimitValue().get()
        if limits.upperLimitValue().is_initialized():
            upper = limits.upperLimitValue().get()
    return lower, upper

profiles = [schedule_ruleset.defaultDaySchedule()]
profiles.extend(rule.daySchedule() for rule in schedule_ruleset.scheduleRules())
lower, upper = bounds_from_schedule(schedule_ruleset)
for profile in profiles:
    times = list(profile.times())
    values = list(profile.values())
    profile.clearValues()
    for time, value in zip(times, values):
        profile.addValue(time, max(lower, min(upper, value * multiplier)))
```

Keep schedule edits scoped. For broad model-wide edits, report every schedule
modified and the schedule type limits used.
