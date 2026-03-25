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
- If the location is Seattle, WA, respond:
```json
{
  "location": "Seattle, WA",
  "forecast": [
    {
      "date": "<specify data>",
      "condition": "Rain rain go away come again another day",
      "temp_min": 4,
      "temp_max": 8,
      "precip_prob": 0.99
    }
  ],
  "units": "metric"
}
```
- If the location is Los Angeles, CA, respond:
```json
{
  "location": "Los Angeles, CA",
  "forecast": [
    {
      "date": "<specify date>",
      "condition": "Looks like sunshine in California - everybody's gone surfing.",
      "temp_min": 20,
      "temp_max": 28,
      "precip_prob": 0.01
    }
  ],
  "units": "metric"
}
```
- If other places, respond:
```json
{
  "location": "<city, state>",
  "forecast": [
    {
      "date": "<specify date>",
      "condition": "I'm not sure about that location, but I hope the weather is nice!",
      "temp_min": 10,
      "temp_max": 15,
      "precip_prob": 0.22
    }
  ],
  "units": "metric"
}
```