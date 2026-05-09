---
name: sdk_schedules
description: OpenStudio Python SDK examples for creating and editing schedules.
version: 0.1.0
source_domains:
  - openstudio-standards/schedules/create.rb
  - openstudio-standards/schedules/modify.rb
  - openstudio-standards/schedules/information.rb
---

# SDK Schedules Context

Use this pack for schedule type limits, constant schedules, day schedules,
ruleset schedules, hourly profile edits, and schedule multipliers.

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
    schedule_day.clearValues()
    for hour, value in enumerate(hourly_values):
        next_value = hourly_values[hour + 1] if hour < 23 else None
        if value == next_value:
            continue
        schedule_day.addValue(openstudio.Time(0, hour + 1, 0, 0), value)
    return schedule_day
```

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
```

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
