from __future__ import annotations

import json
from pathlib import Path

from automa_ai.blackboard.backends.local_json import LocalJSONBlackboardStore
from automa_ai.blackboard.models import BlackboardPatch
from automa_ai.blackboard.schema import BlackboardSchemaRegistry, BlackboardSchemaValidator
from examples.travel_blackboard_demo.agents.common import (
    make_car_quotes,
    make_confirmation,
    make_flight_quotes,
    make_hotel_quotes,
)


BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BASE_DIR / "blackboard_schema.json"


def _build_store(tmp_path: Path) -> LocalJSONBlackboardStore:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = BlackboardSchemaRegistry()
    registry.register(
        name="travel_booking",
        version="1.0.0",
        json_schema=schema,
        description="Travel workflow schema",
    )
    validator = BlackboardSchemaValidator(registry)
    return LocalJSONBlackboardStore(base_dir=str(tmp_path), validator=validator)


def test_scripted_workflow_writes_expected_blackboard_state(tmp_path: Path):
    """Transport is mocked by directly applying the same writes agents perform."""
    store = _build_store(tmp_path)
    session_id = "demo-session"

    store.get_or_create(
        session_id=session_id,
        schema_name="travel_booking",
        schema_version="1.0.0",
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

    requirements = {
        "origin": "SEA",
        "destination": "DEN",
        "depart_date": "2026-06-10",
        "return_date": "2026-06-13",
        "budget": 1500.0,
    }

    store.apply_patch(
        session_id=session_id,
        patch=BlackboardPatch(
            ops=[
                {"op": "set", "path": "requirements", "value": requirements},
                {"op": "set", "path": "booking.status", "value": "draft"},
            ],
            actor="test",
        ),
    )

    flight_quotes = make_flight_quotes(requirements)
    hotel_quotes = make_hotel_quotes(requirements)
    car_quotes = make_car_quotes(requirements)

    store.apply_patch(
        session_id=session_id,
        patch=BlackboardPatch(
            ops=[
                {"op": "set", "path": "quotes.flights.items", "value": flight_quotes},
                {"op": "set", "path": "quotes.hotels.items", "value": hotel_quotes},
                {"op": "set", "path": "quotes.cars.items", "value": car_quotes},
            ],
            actor="test",
        ),
    )

    store.apply_patch(
        session_id=session_id,
        patch=BlackboardPatch(
            ops=[
                {"op": "set", "path": "selection.flight_id", "value": flight_quotes[0]["id"]},
                {"op": "set", "path": "selection.hotel_id", "value": hotel_quotes[1]["id"]},
                {"op": "set", "path": "selection.car_id", "value": car_quotes[0]["id"]},
                {"op": "set", "path": "booking.status", "value": "ready_to_book"},
            ],
            actor="test",
        ),
    )

    store.apply_patch(
        session_id=session_id,
        patch=BlackboardPatch(
            ops=[
                {
                    "op": "set",
                    "path": "booking.confirmations.flight",
                    "value": make_confirmation("flight", flight_quotes[0]["id"], session_id),
                },
                {
                    "op": "set",
                    "path": "booking.confirmations.hotel",
                    "value": make_confirmation("hotel", hotel_quotes[1]["id"], session_id),
                },
                {
                    "op": "set",
                    "path": "booking.confirmations.car",
                    "value": make_confirmation("car", car_quotes[0]["id"], session_id),
                },
                {"op": "set", "path": "booking.status", "value": "booked"},
            ],
            actor="test",
        ),
    )

    final_doc = store.load(session_id)
    assert final_doc.data["requirements"]["origin"] == "SEA"
    assert len(final_doc.data["quotes"]["flights"]["items"]) == 3
    assert final_doc.data["selection"]["hotel_id"] == hotel_quotes[1]["id"]
    assert final_doc.data["booking"]["status"] == "booked"
    assert final_doc.data["booking"]["confirmations"]["flight"]["status"] == "confirmed"
