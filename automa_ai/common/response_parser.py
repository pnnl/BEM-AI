import json
import re
from typing import Tuple, List, Optional, Dict, Any


def extract_and_parse_json(text: str, parse_first: bool = False) -> Tuple[List[str], Optional[Dict[Any, Any]]]:
    """
    Extract all JSON strings from text and parse either the first or last one.

    Args:
        text (str): Input text containing JSON strings
        parse_first (bool): If True, parse the first JSON found; if False, parse the last one

    Returns:
        Tuple[List[str], Optional[Dict[Any, Any]]]:
            - List of all extracted JSON strings
            - Parsed dictionary from the first/last JSON string (None if no valid JSON found)
    """
    json_strings = []
    target_parsed_json = None

    # Find all potential JSON blocks starting with { and ending with }
    i = 0

    while i < len(text):
        if text[i] == '{':
            # Found start of potential JSON, now find the matching closing brace
            brace_count = 1
            j = i + 1
            in_string = False
            escape_next = False

            while j < len(text) and brace_count > 0:
                char = text[j]

                if escape_next:
                    escape_next = False
                elif char == '\\' and in_string:
                    escape_next = True
                elif char == '"' and not escape_next:
                    in_string = not in_string
                elif not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1

                j += 1

            if brace_count == 0:
                # Found complete JSON block
                potential_json = text[i:j]

                # Try to parse it to validate it's actual JSON
                try:
                    parsed = json.loads(potential_json)
                    json_strings.append(potential_json)

                    # Set target_parsed_json based on parse_first flag
                    if parse_first and target_parsed_json is None:
                        # For first: only set if we haven't set it yet
                        target_parsed_json = parsed
                    elif not parse_first:
                        # For last: keep updating with each valid JSON found
                        target_parsed_json = parsed

                    # Skip past this entire JSON to avoid extracting nested objects
                    i = j
                    continue

                except (json.JSONDecodeError, ValueError):
                    # Not valid JSON, continue searching
                    raise Exception(f"Failed parsing JSON: {text}")

        i += 1

    # If empty, raise exception
    assert target_parsed_json is not None
    assert json_strings

    return json_strings, target_parsed_json


def extract_and_parse_json_regex_fallback(text: str) -> Tuple[List[str], Optional[Dict[Any, Any]]]:
    """
    Alternative implementation using regex as fallback.
    Less robust for nested structures but faster for simple cases.

    Args:
        text (str): Input text containing JSON strings

    Returns:
        Tuple[List[str], Optional[Dict[Any, Any]]]:
            - List of all extracted JSON strings
            - Parsed dictionary from the last JSON string (None if no valid JSON found)
    """
    json_strings = []
    last_parsed_json = None

    # Find all text blocks that start with { and end with }
    # This regex is less robust but can serve as a fallback
    pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'

    for match in re.finditer(pattern, text):
        potential_json = match.group()
        try:
            parsed = json.loads(potential_json)
            json_strings.append(potential_json)
            last_parsed_json = parsed
        except (json.JSONDecodeError, ValueError):
            raise Exception(f"Failed parsing JSON: {text}")

    return json_strings, last_parsed_json