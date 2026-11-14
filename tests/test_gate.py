"""gate_v1's decision against the hand-written tests/vectors/gate_vectors.json."""

import json
from pathlib import Path

import pytest

from archways_assistant.fakebackend import AND_V3_RULES
from archways_assistant.feedindex import feed_row
from archways_assistant.rank import gate_v1, points, question_terms

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "tests" / "vectors" / "gate_vectors.json").read_text("utf-8"))
BY_ID = {row["id"]: row for row in (feed_row(d)[0] for d in DATA["details"])}
CASES = DATA["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:3] for c in CASES])
def test_gate_vectors(case):
    row = BY_ID[case["top_id"]]
    title, body = row["title"].lower(), row["body"].lower()
    synonyms = AND_V3_RULES[case["matcher"]]
    terms = question_terms(case["question"])
    assert points(terms, title, body, synonyms) == case["points"]
    assert terms.possible == case["possible"]
    p, q = case["theta"]
    assert gate_v1(case["question"], title, body, synonyms, p, q) is case["passes"]


def test_gate_rejects_a_bad_theta():
    with pytest.raises(ValueError):
        gate_v1("q", "t", "b", AND_V3_RULES["and_v3"], 1, 0)
