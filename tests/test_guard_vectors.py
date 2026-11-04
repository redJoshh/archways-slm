"""tests/vectors/guard_vectors.json must match the current guard.

guard-ts runs the same vectors (guard-ts/test/vectors.test.ts). After a
guard change, run: uv run python scripts/export_guard_vectors.py --refresh
and change guard-ts to match.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from archways_assistant.e2escore import (
    FALLBACK_HEADER,
    GUARD_SPACES,
    LAST_RESORT_MESSAGE,
    NON_ASCII_DIGIT_RANGES,
    guard,
)

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tests" / "vectors" / "guard_vectors.json"
RAW = PATH.read_bytes()
DOC = json.loads(RAW)
VECTORS = DOC["vectors"]
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text(
        encoding="utf-8"
    )
)
# Without a format checker: posted_at's format is the guard's job (an
# unreadable one gives the last-resort reply).
RESULT_SHAPE = Draft202012Validator(
    {"$defs": CONTRACT["$defs"], "$ref": "#/$defs/result"}
)


def test_file_is_ascii_with_lf_line_endings():
    RAW.decode("ascii")
    assert b"\r" not in RAW


def test_spec_matches_the_guard_constants():
    assert DOC["spec"] == {
        "guard_spaces": [ord(ch) for ch in GUARD_SPACES],
        "non_ascii_digit_ranges": [list(r) for r in NON_ASCII_DIGIT_RANGES],
        "fallback_header": FALLBACK_HEADER,
        "last_resort_message": LAST_RESORT_MESSAGE,
    }


def test_every_source_type_is_present():
    kinds = {s.split(":", 1)[0] for v in VECTORS for s in v["sources"]}
    assert kinds == {"unit", "edge", "phone", "run"}


def test_ids_are_unique_and_inputs_are_not_repeated():
    assert len({v["id"] for v in VECTORS}) == len(VECTORS)
    inputs = {json.dumps(v["input"], sort_keys=True) for v in VECTORS}
    assert len(inputs) == len(VECTORS)


def test_vectors_cover_firing_last_resort_and_every_code_kind():
    texts = [v["expected"]["text"] for v in VECTORS]
    assert LAST_RESORT_MESSAGE in texts
    assert any(t.startswith(FALLBACK_HEADER) for t in texts)
    codes = {c.split(":", 1)[0] for v in VECTORS for c in v["expected"]["codes"]}
    assert codes == {
        "unsupported_date",
        "unsupported_number",
        "non_ascii_digit",
        "filtered_text",
    }


def has_lone_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_vector_matches_the_guard(vector):
    inp = vector["input"]
    strings = [inp["reply"], inp["question"], *inp["forbidden"]]
    strings += [r["title"] + r["excerpt"] for r in inp["results"]]
    assert not any(has_lone_surrogate(s) for s in strings)
    RESULT_SHAPE.validate(inp["results"])
    result = guard(inp["reply"], inp["results"], inp["question"], inp["forbidden"])
    assert vector["expected"] == {
        "fired": result.fired,
        "codes": list(result.codes),
        "text": result.text,
    }
    assert vector["python_reasons"] == list(result.reasons)
