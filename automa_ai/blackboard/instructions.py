from __future__ import annotations

from automa_ai.blackboard.schema import BlackboardSchema


def build_blackboard_contract(schema: BlackboardSchema) -> str:
    return (
        "## SHARED SESSION BLACKBOARD CONTRACT\n"
        "This workflow uses a session-scoped blackboard document as the source of truth.\n"
        "Always read/write shared fields through blackboard tools only; never invent state.\n"
        "If data is missing, ask the user or invoke tools/subagents to populate it.\n"
        "Use optimistic concurrency with expected_revision for updates where possible.\n"
        "When upstream fields change, write updates that invalidate/recompute derived sections.\n"
        f"Schema: {schema.name} v{schema.version}.\n"
        f"Schema description: {schema.description or 'N/A'}.\n"
        "Available fields follow this JSON Schema:\n"
        f"{schema.json_schema}"
    )
