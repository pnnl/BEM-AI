from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

from automa_ai.blackboard.errors import SchemaValidationError

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


@dataclass(frozen=True)
class BlackboardSchema:
    name: str
    version: str
    json_schema: dict[str, Any]
    description: str | None = None


class BlackboardSchemaRegistry:
    def __init__(self):
        self._schemas: dict[tuple[str, str], BlackboardSchema] = {}

    def register(
        self,
        name: str,
        version: str,
        json_schema: dict[str, Any],
        description: str | None = None,
    ) -> None:
        self._schemas[(name, version)] = BlackboardSchema(
            name=name,
            version=version,
            json_schema=json_schema,
            description=description,
        )

    def resolve(self, name: str, version: str) -> BlackboardSchema:
        key = (name, version)
        if key not in self._schemas:
            raise SchemaValidationError(f"Schema '{name}:{version}' is not registered.")
        return self._schemas[key]


class BlackboardSchemaValidator:
    _fallback_warning_emitted = False

    def __init__(self, registry: BlackboardSchemaRegistry):
        self.registry = registry

    def validate(self, name: str, version: str, data: dict[str, Any]) -> None:
        schema = self.registry.resolve(name, version)
        if jsonschema is not None:
            try:
                jsonschema.validate(data, schema.json_schema)
            except jsonschema.ValidationError as exc:
                raise SchemaValidationError(str(exc)) from exc
            return

        if not BlackboardSchemaValidator._fallback_warning_emitted:
            warnings.warn(
                "jsonschema is not installed; blackboard schema validation is running in fallback mode "
                "with limited keyword support. Install jsonschema for full validation coverage.",
                RuntimeWarning,
                stacklevel=2,
            )
            BlackboardSchemaValidator._fallback_warning_emitted = True

        self._fallback_validate(schema.json_schema, data)

    def _fallback_validate(self, schema: dict[str, Any], data: Any, path: str = "$") -> None:
        schema_type = schema.get("type")
        if schema_type == "object":
            if not isinstance(data, dict):
                raise SchemaValidationError(f"{path} must be an object.")
            required = schema.get("required", [])
            for key in required:
                if key not in data:
                    raise SchemaValidationError(f"{path}.{key} is required.")
            properties = schema.get("properties", {})
            for key, value in data.items():
                if key in properties:
                    self._fallback_validate(properties[key], value, f"{path}.{key}")
        elif schema_type == "array":
            if not isinstance(data, list):
                raise SchemaValidationError(f"{path} must be an array.")
            item_schema = schema.get("items")
            if item_schema:
                for idx, value in enumerate(data):
                    self._fallback_validate(item_schema, value, f"{path}[{idx}]")
        elif schema_type == "string":
            if not isinstance(data, str):
                raise SchemaValidationError(f"{path} must be a string.")
        elif schema_type == "integer":
            if not isinstance(data, int) or isinstance(data, bool):
                raise SchemaValidationError(f"{path} must be an integer.")
        elif schema_type == "number":
            if not isinstance(data, (int, float)) or isinstance(data, bool):
                raise SchemaValidationError(f"{path} must be a number.")
        elif schema_type == "boolean":
            if not isinstance(data, bool):
                raise SchemaValidationError(f"{path} must be a boolean.")
        elif schema_type == "null":
            if data is not None:
                raise SchemaValidationError(f"{path} must be null.")
