import json

import pytest

from automa_ai.common.response_parser import extract_and_parse_json


class TestJSONExtractor:
    """Test cases for JSON extraction and parsing functions."""

    def test_single_json(self):
        """Test extraction of a single JSON object."""
        text = 'Here is some data: {"name": "John", "age": 30} and that\'s it.'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        assert json_list[0] == '{"name": "John", "age": 30}'
        assert last_json == {"name": "John", "age": 30}

        # Test first vs last (should be same for single JSON)
        _, first_json = extract_and_parse_json(text, parse_first=True)
        assert first_json == last_json

    def test_multiple_json_objects(self):
        """Test extraction of multiple JSON objects."""
        text = 'First: {"a": 1} then {"b": 2, "nested": {"c": 3}} finally {"d": 4}'
        json_list, last_json = extract_and_parse_json(text)

        # Should extract exactly 3 JSONs, not 4
        assert len(json_list) == 3
        assert json_list[0] == '{"a": 1}'
        assert json_list[1] == '{"b": 2, "nested": {"c": 3}}'
        assert json_list[2] == '{"d": 4}'
        assert last_json == {"d": 4}

        # Test first JSON parsing
        _, first_json = extract_and_parse_json(text, parse_first=True)
        assert first_json == {"a": 1}

        # Verify the nested JSON is correctly parsed as part of the second object
        assert json_list[1] == '{"b": 2, "nested": {"c": 3}}'
        parsed_second = json.loads(json_list[1])
        assert parsed_second == {"b": 2, "nested": {"c": 3}}

    def test_nested_json_with_string_braces(self):
        """Test JSON with nested objects and strings containing braces."""
        text = 'Result: {"message": "Status: {success}", "data": {"items": [1, 2, 3]}}'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        expected = {"message": "Status: {success}", "data": {"items": [1, 2, 3]}}
        assert last_json == expected

    def test_json_with_escaped_quotes(self):
        """Test JSON containing escaped quotes."""
        text = 'Info: {"description": "He said \\"Hello\\" to me", "status": "ok"}'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        assert last_json == {"description": 'He said "Hello" to me', "status": "ok"}

    def test_mixed_valid_invalid_json(self):
        """Test text with both valid and invalid JSON."""
        text = 'Bad: {invalid json} Good: {"valid": true} Bad again: {another bad}'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        assert json_list[0] == '{"valid": true}'
        assert last_json == {"valid": True}

    def test_no_json_in_text(self):
        """Test text with no JSON objects."""
        text = 'This text has no JSON at all.'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 0
        assert last_json is None

        # Test first JSON parsing with no JSON
        _, first_json = extract_and_parse_json(text, parse_first=True)
        assert first_json is None

    def test_empty_json_objects(self):
        """Test empty JSON objects and arrays."""
        text = 'Empty object: {} and that\'s it'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        assert json_list[0] == '{}'
        assert last_json == {}

    def test_complex_nested_structure(self):
        """Test complex nested JSON structure."""
        text = 'Complex: {"users": [{"name": "Alice", "profile": {"age": 25, "city": "NYC"}}, {"name": "Bob"}], "meta": {"total": 2}}'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        expected = {
            "users": [
                {"name": "Alice", "profile": {"age": 25, "city": "NYC"}},
                {"name": "Bob"}
            ],
            "meta": {"total": 2}
        }
        assert last_json == expected

    def test_parse_first_vs_last_flag(self):
        """Test the parse_first flag behavior with multiple JSONs."""
        text = 'Start: {"first": 1, "value": "a"} Middle: {"second": 2, "value": "b"} End: {"third": 3, "value": "c"}'

        # Test last JSON (default)
        json_list_last, last_json = extract_and_parse_json(text, parse_first=False)
        assert len(json_list_last) == 3
        assert last_json == {"third": 3, "value": "c"}

        # Test first JSON
        json_list_first, first_json = extract_and_parse_json(text, parse_first=True)
        assert len(json_list_first) == 3  # Same list of extracted JSONs
        assert first_json == {"first": 1, "value": "a"}

        # Ensure the JSON lists are identical
        assert json_list_first == json_list_last

    def test_json_with_arrays(self):
        """Test JSON containing arrays."""
        text = 'Data: {"numbers": [1, 2, 3], "strings": ["a", "b", "c"], "mixed": [1, "two", {"three": 3}]}'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        expected = {
            "numbers": [1, 2, 3],
            "strings": ["a", "b", "c"],
            "mixed": [1, "two", {"three": 3}]
        }
        assert last_json == expected

    def test_json_with_special_characters(self):
        """Test JSON with special characters and unicode."""
        text = 'Special: {"emoji": "😀", "unicode": "café", "symbols": "!@#$%^&*()"}'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        assert last_json == {"emoji": "😀", "unicode": "café", "symbols": "!@#$%^&*()"}

    def test_json_with_null_and_boolean_values(self):
        """Test JSON with null and boolean values."""
        text = 'Values: {"null_value": null, "true_value": true, "false_value": false, "number": 42}'
        json_list, last_json = extract_and_parse_json(text)

        assert len(json_list) == 1
        assert last_json == {
            "null_value": None,
            "true_value": True,
            "false_value": False,
            "number": 42
        }

    def test_adjacent_json_objects(self):
        """Test JSON objects that are adjacent to each other."""
        text = 'Data: {"first": 1}{"second": 2} more text'
        json_list, last_json = extract_and_parse_json(text)

        # Should extract both JSONs separately
        assert len(json_list) == 2
        assert json_list[0] == '{"first": 1}'
        assert json_list[1] == '{"second": 2}'
        assert last_json == {"second": 2}

        _, first_json = extract_and_parse_json(text, parse_first=True)
        assert first_json == {"first": 1}

    def test_real_world_energyplus_example(self):
        """Test the specific EnergyPlus example that was causing issues."""
        json_text = '''{
      "original_query": "Tell me what materials used in the a Construction object named 'Typical Wood Joist Attic Floor R-37.04 1'?",
      "model_info": {
        "model_path": "/Users/in.idf"
      },
      "tasks": [
        {
            "id": 1,
            "description": "I need help to understand the EnergyPlus schema: Construction"
        },
        {
            "id": 2,
            "description": "I need to help find out EnergyPlus objects that are referenced by this object Typical Wood Joist Attic Floor R-37.04 1"
        }
      ]
    }'''
        json_list, last_json = extract_and_parse_json(json_text)

        # Should extract only 1 JSON (the complete object), not 3 separate ones
        assert len(json_list) == 1

        # Verify the complete structure
        assert "original_query" in last_json
        assert "model_info" in last_json
        assert "tasks" in last_json
        assert len(last_json["tasks"]) == 2
        assert last_json["tasks"][0]["id"] == 1
        assert last_json["tasks"][1]["id"] == 2

    def test_real_world_response(self):
        """Test """
        json_text='{\n    "original_query": "I have a model in local directory: user/os.osm, I want to update the model window to wall ratio to 0.35",\n    "blackboard":\n    {\n        "model_path": "user/os.osm",\n        "window_to_wall_ratio": 0.35,\n        "building_type": "small office"\n    },\n    "tasks": [\n        {\n            "id": 1,\n            "description": "Load energy model from user provided path",\n            "status": "pending",\n            "agent": "Energy Model Geometry Agent"\n        }, \n        {\n            "id": 2,\n            "description": "Update window to wall ratio to 0.35 in the energy model",\n            "status": "pending",\n            "agent": "Energy Model Geometry Agent"\n        }\n    ],\n    "status": "ready_to_execute",\n    "question": "Should the updated model be saved to a new file path, or overwrite the original file at user/os.osm?"\n}'
        json_list, last_json = extract_and_parse_json(json_text)

        # Should extract only 1 JSON (the complete object), not 3 separate ones
        assert len(json_list) == 1

        # Verify the complete structure
        assert "original_query" in last_json
        assert "blackboard" in last_json
        assert "tasks" in last_json
        assert len(last_json["tasks"]) == 2
        assert last_json["tasks"][0]["id"] == 1
        assert last_json["tasks"][1]["id"] == 2


    def test_real_world_conversation(self):
        # This test is expecting the function to raise exception
        text = """
        ### Task
The user has asked to know more about me, seeking information about my capabilities, purpose, or background.

### Building Energy Modeling Task
Since there are no specific results provided related to building energy modeling, it appears this query does not pertain to that domain directly. The task seems to be a general inquiry about myself.

### Modeling Meta Data
Without access to specific meta data (blackboard), the summary relies on understanding the nature of the query itself. The user's question implies a desire for self-description or an explanation of my functions and limitations.

### Summary
This task involves providing a personal description in response to the user's inquiry about me. Given the context, I am an artificial intelligence designed to process and respond to natural language inputs, capable of answering questions, generating text, and engaging in conversation on a wide range of topics. My purpose is to assist users by offering information, solving problems, and providing entertainment through text-based interactions.
        """
        with pytest.raises(AssertionError) as e:
            json_list, last_json = extract_and_parse_json(text)
