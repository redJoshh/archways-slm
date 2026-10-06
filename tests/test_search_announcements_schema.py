import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_PATH = (
    Path(__file__).parent.parent / "contracts" / "search_announcements.schema.json"
)
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_ID = SCHEMA["$id"]
REGISTRY = Registry().with_resource(SCHEMA_ID, Resource.from_contents(SCHEMA))


def validator_for(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        {"$ref": f"{SCHEMA_ID}#/$defs/{name}"},
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )


ARGUMENTS = validator_for("arguments")
RESULT = validator_for("result")


def announcement(**overrides):
    item = {
        "id": "a1",
        "title": "Enrollment schedule",
        "excerpt": "Enrollment for the second term opens on Monday.",
        "office": "Registrar",
        "priority": "HIGH",
        "year_level": 2,
        "posted_at": "2026-10-06T09:00:00+08:00",
    }
    item.update(overrides)
    return item


def without(key):
    item = announcement()
    del item[key]
    return item


def test_schema_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


def test_schema_id_is_versioned():
    assert SCHEMA_ID.endswith(":v1")


def keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys(value)


def test_arguments_have_no_refs():
    assert "$ref" not in set(keys(SCHEMA["$defs"]["arguments"]))


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "enrollment"},
        {"query": "enrollment", "days": 1, "limit": 1},
        {"query": "enrollment", "days": 30, "limit": 10},
        {"query": "x" * 200},
    ],
)
def test_valid_arguments(payload):
    ARGUMENTS.validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"days": 7},
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 201},
        {"query": "enrollment", "days": 0},
        {"query": "enrollment", "days": 31},
        {"query": "enrollment", "days": 99},
        {"query": "enrollment", "limit": 0},
        {"query": "enrollment", "limit": 11},
        {"query": "enrollment", "days": "7"},
        {"query": "enrollment", "days": 7.5},
        {"query": "enrollment", "office": "Registrar"},
    ],
)
def test_invalid_arguments(payload):
    assert not ARGUMENTS.is_valid(payload)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [announcement()],
        [announcement(year_level=None)],
        [announcement(posted_at="2026-10-06T01:00:00Z")],
        [announcement(id=str(i)) for i in range(10)],
    ],
)
def test_valid_result(payload):
    RESULT.validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        *[[without(key)] for key in SCHEMA["$defs"]["announcement"]["required"]],
        [announcement(title="x" * 256)],
        [announcement(excerpt="x" * 501)],
        [announcement(year_level="2")],
        [announcement(title=123)],
        [announcement(posted_at="2026-10-06T09:00:00")],
        [announcement(posted_at="yesterday")],
        [announcement(posted_at="2026-13-01T09:00:00Z")],
        [announcement(author_id="u1")],
        [announcement(revision_remarks="fixed typo")],
        [announcement(summary="old field name")],
        [announcement(id=str(i)) for i in range(11)],
        announcement(),
    ],
)
def test_invalid_result(payload):
    assert not RESULT.is_valid(payload)
