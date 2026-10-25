import json

import pytest
from jsonschema import Draft202012Validator

from archways_assistant.formatschema import build_format_schema, unwrap_reply
from archways_assistant.tooldef import SCHEMA_PATH

CONTRACT = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
FORMAT = build_format_schema(CONTRACT)
VALIDATOR = Draft202012Validator(FORMAT)


def test_format_schema_is_valid_json_schema():
    Draft202012Validator.check_schema(FORMAT)


def test_call_branch_uses_the_contract_arguments_unchanged():
    call = FORMAT["anyOf"][0]
    assert call["properties"]["name"] == {"const": CONTRACT["title"]}
    assert call["properties"]["arguments"] == CONTRACT["$defs"]["arguments"]


def test_builder_copies_rather_than_aliases_the_contract():
    FORMAT["anyOf"][0]["properties"]["arguments"]["required"].append("x")
    try:
        assert CONTRACT["$defs"]["arguments"]["required"] == ["query"]
    finally:
        FORMAT["anyOf"][0]["properties"]["arguments"]["required"].pop()


@pytest.mark.parametrize(
    "value",
    [
        {"name": "search_announcements", "arguments": {"query": "enrollment"}},
        {
            "name": "search_announcements",
            "arguments": {"query": "scholarship", "days": 30, "limit": 10},
        },
        {"reply": "I can only offer guidance based on official announcements."},
        {"reply": ""},
    ],
)
def test_accepts_calls_and_replies(value):
    assert VALIDATOR.is_valid(value)


@pytest.mark.parametrize(
    "value",
    [
        {"name": "freshmen orientation", "arguments": {"query": "orientation"}},
        {"name": "search_announcements", "arguments": {}},
        {"name": "search_announcements", "arguments": {"query": "x", "days": 60}},
        {"name": "search_announcements", "arguments": {"query": "x", "date": "y"}},
        {"name": "search_announcements"},
        {"reply": 3},
        {"reply": "hi", "name": "search_announcements"},
        {},
        "plain text",
    ],
)
def test_rejects_other_shapes(value):
    assert not VALIDATOR.is_valid(value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"reply": "Hello."}', "Hello."),
        ('  {"reply": ""}\n', ""),
        ('{"name": "search_announcements", "arguments": {"query": "x"}}', None),
        ('{"reply": "a", "extra": 1}', None),
        ('{"reply": 5}', None),
        ("Hello.", None),
        ('{"reply": "a"', None),
    ],
)
def test_unwrap_reply(text, expected):
    assert unwrap_reply(text) == expected
