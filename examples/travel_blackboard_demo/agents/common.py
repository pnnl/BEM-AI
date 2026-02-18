from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from automa_ai.config.blackboard import BlackboardConfig
from automa_ai.tools.base import BaseDefaultTool, RuntimeDeps
from automa_ai.tools.registry import DEFAULT_TOOL_REGISTRY


def _stable_rng(*parts: str) -> random.Random:
    joined = "|".join(parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _stable_id(prefix: str, *parts: str) -> str:
    joined = "|".join((prefix, *parts))
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:10]}"


def make_flight_quotes(requirements: dict[str, Any], top_k: int = 3) -> list[dict[str, Any]]:
    origin = requirements.get("origin", "UNKNOWN")
    destination = requirements.get("destination", "UNKNOWN")
    depart_date = requirements.get("depart_date", "TBD")
    return_date = requirements.get("return_date", "TBD")
    budget = float(requirements.get("budget", 1200))
    rng = _stable_rng("flight", origin, destination, depart_date, return_date, str(budget))

    quotes: list[dict[str, Any]] = []
    for idx in range(top_k):
        carrier = ["Automa Air", "GraphJet", "ToolCall Airlines"][idx % 3]
        price = round(min(budget, budget * 0.55 + rng.randint(30, 220) + idx * 19), 2)
        quote_id = _stable_id("flt", origin, destination, depart_date, str(idx))
        quotes.append(
            {
                "id": quote_id,
                "provider": carrier,
                "price": price,
                "depart_time": f"{8 + idx * 2:02d}:15",
                "arrival_time": f"{11 + idx * 2:02d}:40",
                "cabin": "economy",
                "stale": False,
            }
        )
    return quotes


def make_hotel_quotes(requirements: dict[str, Any], top_k: int = 3) -> list[dict[str, Any]]:
    destination = requirements.get("destination", "UNKNOWN")
    checkin = requirements.get("depart_date", "TBD")
    checkout = requirements.get("return_date", "TBD")
    budget = float(requirements.get("budget", 1200))
    rng = _stable_rng("hotel", destination, checkin, checkout, str(budget))

    quotes: list[dict[str, Any]] = []
    for idx in range(top_k):
        nightly = round(min(budget / 3, 90 + rng.randint(10, 65) + idx * 14), 2)
        quote_id = _stable_id("htl", destination, checkin, str(idx))
        quotes.append(
            {
                "id": quote_id,
                "provider": ["CityStay", "Zen Suites", "Orbit Inn"][idx % 3],
                "nightly_rate": nightly,
                "total_estimate": round(nightly * 3, 2),
                "rating": round(3.8 + idx * 0.3, 1),
                "stale": False,
            }
        )
    return quotes


def make_car_quotes(requirements: dict[str, Any], top_k: int = 3) -> list[dict[str, Any]]:
    destination = requirements.get("destination", "UNKNOWN")
    pickup = requirements.get("depart_date", "TBD")
    dropoff = requirements.get("return_date", "TBD")
    rng = _stable_rng("car", destination, pickup, dropoff)

    quotes: list[dict[str, Any]] = []
    for idx in range(top_k):
        daily = round(38 + rng.randint(0, 25) + idx * 7, 2)
        quote_id = _stable_id("car", destination, pickup, str(idx))
        quotes.append(
            {
                "id": quote_id,
                "provider": ["RoadRunner", "DriveFlow", "Maple Mobility"][idx % 3],
                "class": ["economy", "compact suv", "midsize"][idx % 3],
                "daily_rate": daily,
                "total_estimate": round(daily * 3, 2),
                "stale": False,
            }
        )
    return quotes


def make_confirmation(category: str, quote_id: str, session_id: str) -> dict[str, Any]:
    return {
        "quote_id": quote_id,
        "confirmation_id": _stable_id("cnf", category, quote_id, session_id),
        "status": "confirmed",
    }


class RequirementsInput(BaseModel):
    origin: str
    destination: str
    depart_date: str
    return_date: str
    budget: float = Field(gt=0)


class BookingInput(BaseModel):
    category: str
    quote_id: str
    session_id: str


class TravelFlightTool(BaseDefaultTool):
    type = "travel_flight_provider"
    description = "Generate deterministic mock flight quotes from user travel requirements."
    args_schema = RequirementsInput

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"items": make_flight_quotes(payload)}


class TravelHotelTool(BaseDefaultTool):
    type = "travel_hotel_provider"
    description = "Generate deterministic mock hotel quotes from user travel requirements."
    args_schema = RequirementsInput

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"items": make_hotel_quotes(payload)}


class TravelCarTool(BaseDefaultTool):
    type = "travel_car_provider"
    description = "Generate deterministic mock car rental quotes from user travel requirements."
    args_schema = RequirementsInput

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"items": make_car_quotes(payload)}


class TravelBookingTool(BaseDefaultTool):
    type = "travel_booking_provider"
    description = "Create deterministic booking confirmations from selected quote IDs."
    args_schema = BookingInput

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        return make_confirmation(payload["category"], payload["quote_id"], payload["session_id"])


def build_travel_flight_tool(_config: dict[str, Any], _deps: RuntimeDeps) -> BaseDefaultTool:
    return TravelFlightTool()


def build_travel_hotel_tool(_config: dict[str, Any], _deps: RuntimeDeps) -> BaseDefaultTool:
    return TravelHotelTool()


def build_travel_car_tool(_config: dict[str, Any], _deps: RuntimeDeps) -> BaseDefaultTool:
    return TravelCarTool()


def build_travel_booking_tool(_config: dict[str, Any], _deps: RuntimeDeps) -> BaseDefaultTool:
    return TravelBookingTool()


def register_travel_tools() -> None:
    tool_builders = {
        TravelFlightTool.type: build_travel_flight_tool,
        TravelHotelTool.type: build_travel_hotel_tool,
        TravelCarTool.type: build_travel_car_tool,
        TravelBookingTool.type: build_travel_booking_tool,
    }
    for tool_type, builder in tool_builders.items():
        try:
            DEFAULT_TOOL_REGISTRY.register(tool_type, builder)
        except ValueError:
            # Ignore duplicate registration when module is imported multiple times.
            pass


def load_blackboard_config(schema_path: Path, base_dir: Path) -> BlackboardConfig:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return BlackboardConfig(
        enabled=True,
        backend="local_json",
        base_dir=str(base_dir),
        schema_name="travel_booking",
        schema_version="1.0.0",
        schema_description="Travel planning and booking shared state.",
        schema=schema,
        initial_data={
            "requirements": {},
            "quotes": {
                "flights": {"items": [], "stale": False},
                "hotels": {"items": [], "stale": False},
                "cars": {"items": [], "stale": False},
            },
            "selection": {},
            "booking": {"status": "draft", "confirmations": {}},
        },
    )


def blackboard_file_path(base_dir: Path, session_id: str) -> Path:
    return base_dir / f"{session_id}.blackboard.json"
