import copy
import json

import pytest

from archways_assistant.tooldef import (
    OUTPUT_PATH,
    SCHEMA_PATH,
    build_tool_definition,
    render,
)

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
GENERATED_TEXT = OUTPUT_PATH.read_text(encoding="utf-8")
GENERATED = json.loads(GENERATED_TEXT)
PROPERTIES = GENERATED["function"]["parameters"]["properties"]

DROPPED_KEYWORDS = {
    "$comment",
    "$ref",
    "additionalProperties",
    "pattern",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "default",
    "format",
}


def keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys(value)


def test_generated_file_is_up_to_date():
    assert GENERATED_TEXT == render(build_tool_definition(SCHEMA))


def test_generated_file_has_no_dropped_keywords():
    assert DROPPED_KEYWORDS.isdisjoint(keys(GENERATED))


def test_required_is_query():
    assert GENERATED["function"]["parameters"]["required"] == ["query"]


def test_property_names_match_schema():
    assert list(PROPERTIES) == list(SCHEMA["$defs"]["arguments"]["properties"])


def test_every_property_has_description():
    for name, prop in PROPERTIES.items():
        assert prop.get("description"), name


def test_golden_descriptions():
    assert {name: prop["description"] for name, prop in PROPERTIES.items()} == {
        "query": (
            "Keywords to search for in announcement titles and text. "
            "Must not be empty. At most 200 characters. "
            "Must contain at least one non-whitespace character."
        ),
        "days": (
            "How many days back to look, by publication date. "
            "Whole number from 1 to 30. Default 7."
        ),
        "limit": (
            "Maximum number of announcements to return. "
            "Whole number from 1 to 10. Default 5."
        ),
    }


def test_sentences_are_derived_from_schema():
    schema = copy.deepcopy(SCHEMA)
    schema["$defs"]["arguments"]["properties"]["days"]["maximum"] = 20
    tool = build_tool_definition(schema)
    days = tool["function"]["parameters"]["properties"]["days"]
    assert "Whole number from 1 to 20." in days["description"]


@pytest.mark.parametrize(
    "extra",
    [
        {"multipleOf": 2},
        {"$ref": "#/$defs/announcement"},
    ],
)
def test_unknown_keyword_raises(extra):
    schema = copy.deepcopy(SCHEMA)
    schema["$defs"]["arguments"]["properties"]["days"].update(extra)
    with pytest.raises(ValueError):
        build_tool_definition(schema)
