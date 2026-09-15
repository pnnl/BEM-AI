# Skill: Predict Weather

## Name
`predict_weather`

## Description
Returns a short-term weather forecast for a given location.

## Inputs
- `location` (string, required): City or location name
- `days_ahead` (integer, optional, default=1): Number of days to forecast (max 7)
- `units` (string, optional): `metric` or `imperial`

## Output
- For Seattle, WA, report rain with a 99% precipitation probability and a 4–8°C range.
- For Los Angeles, CA, report sunshine with a 1% precipitation probability and a 20–28°C range.
- For other locations, state that the forecast is a sample estimate and use a 10–15°C range.
