import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple

# IDD object chunk
def chunk_idd_objects(file_content: str) -> list[str]:
    chunks = []
    current_chunk = []
    object_name = None
    in_object = False
    memo_accumulator = []

    def flush_memo():
        """Combine accumulated memos into one and append to current_chunk."""
        if memo_accumulator:
            combined = " ".join(line.strip()[6:].strip() for line in memo_accumulator)
            current_chunk.append(f"  \\memo {combined}")
            memo_accumulator.clear()

    for line in file_content.splitlines():
        stripped = line.strip()

        # Skip \group lines
        if stripped.lower().startswith(r"\group"):
            continue

        # Start of a new object
        if not line.startswith((" ", "\t")) and stripped.endswith(","):
            if current_chunk and object_name:
                flush_memo()
                chunks.append((object_name, "\n".join(current_chunk)))
                current_chunk = []
            object_name = stripped.rstrip(",")
            in_object = True
            current_chunk.append(line)

        elif in_object:
            if stripped.startswith(r"\memo"):
                memo_accumulator.append(line)
            else:
                flush_memo()
                current_chunk.append(line)
                if stripped.endswith(";"):
                    chunks.append((object_name, "\n".join(current_chunk)))
                    current_chunk = []
                    object_name = None
                    in_object = False

    # Catch any remaining chunk
    if current_chunk and object_name:
        flush_memo()
        chunks.append((object_name, "\n".join(current_chunk)))

    return chunks

# Developed by Check Tools team to chunk a json schema

class SchemaSplitter(ABC):
    def __init__(self, schema_path: str):
        self.schema_path = schema_path
        with open(schema_path) as f:
            self.schema = json.load(f)

    def format_field(self, name: str, field_info: Dict[str, Any]) -> str:
        """
        Format a field into a text chunk.

        Args:
            name: Field name/path
            field_info: Field information dictionary
        """
        lines = [f"Field: {name}", f"Type: {field_info.get("type")}"]

        # Add additional field information
        for key in self.get_field_attributes():
            value = field_info.get(key, "")
            if value:
                lines.append(f"{key.capitalize()}: {value}")

        return "\n".join(lines)

    def get_field_attributes(self) -> List[str]:
        """Get list of field attributes to include in formatting."""
        return ["type"]

    def walk_schema(self, schema: Dict[str, Any], path: str = "") -> List[Tuple[str, Dict[str, Any]]]:
        """
        Walk through a schema and collect field information.

        Args:
            schema: Schema dictionary to walk through
            path: Current path in the schema

        Returns:
            List of tuples containing (field_path, field_info)
        """
        fields = []

        if self.is_field(schema):
            fields.append((path, schema))

        if self.is_object(schema):
            for prop, subschema in self.get_properties(schema).items():
                new_path = f"{path}.{prop}" if path else prop
                fields.extend(self.walk_schema(subschema, new_path))
        elif self.is_array(schema):
            if array_items := self.get_array_items(schema):
                fields.extend(self.walk_schema(array_items, f"{path}[]"))

        return fields

    @abstractmethod
    def is_field(self, schema: Dict[str, Any]) -> bool:
        """Check if schema represents a field."""
        pass

    @abstractmethod
    def is_object(self, schema: Dict[str, Any]) -> bool:
        """Check if schema represents an object type."""
        pass

    @abstractmethod
    def is_array(self, schema: Dict[str, Any]) -> bool:
        """Check if schema represents an array type."""
        pass

    @abstractmethod
    def get_properties(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Get properties from an object schema."""
        pass

    @abstractmethod
    def get_array_items(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Get items definition from an array schema."""
        pass

    def process_schema(self) -> List[str]:
        """Process the schema and return a list of text chunks."""
        fields = self.walk_schema(self.schema)
        return [self.format_field(name, info) for name, info in fields]


class JsonSchemaSplitter(SchemaSplitter):
    schema_type = "JSON Schema"

    def get_field_attributes(self) -> List[str]:
        """Get JSON Schema specific field attributes."""
        field_attributes = super().get_field_attributes()
        return field_attributes + ["description", "$comment", "default", "enum", "descriptions"]

    def is_field(self, schema: Dict[str, Any]) -> bool:
        return "type" in schema

    def is_object(self, schema: Dict[str, Any]) -> bool:
        return schema.get("type") == "object"

    def is_array(self, schema: Dict[str, Any]) -> bool:
        return schema.get("type") == "array"

    def get_properties(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        return schema.get("properties", {})

    def get_array_items(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        return schema.get("items", {})


class OpenSearchSplitter(SchemaSplitter):
    schema_type = "OpenSearch"

    def is_field(self, schema: Dict[str, Any]) -> bool:
        return "type" in schema and not schema.get("properties")

    def is_object(self, schema: Dict[str, Any]) -> bool:
        return bool(schema.get("properties"))

    def is_array(self, schema: Dict[str, Any]) -> bool:
        return isinstance(schema.get("type"), list) or schema.get("type") == "nested"

    def get_properties(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        return schema.get("properties", {})

    def get_array_items(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(schema.get("type"), list):
            return {"type": schema["type"]}
        return schema
