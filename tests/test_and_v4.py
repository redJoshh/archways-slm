"""and_v4 (with rank_v1) against the hand-written tests/vectors/and_v4_vectors.json."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant.fakebackend import AND_V3_RULES, SYNONYMS, SYNONYMS_V2
from archways_assistant.feedindex import feed_row, search_feed
from archways_assistant.rank import points, question_terms

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "and_v4_vectors.json").read_text("utf-8")
)
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text("utf-8")
)
NOW = datetime.fromisoformat(DATA["now"])
ROWS = [feed_row(detail)[0] for detail in DATA["details"]]
BY_ID = {row["id"]: row for row in ROWS}
CASES = [(c, m) for c in DATA["cases"] for m in ("and_v4", "and_v3")]


@pytest.mark.parametrize(
    ("case", "matcher"), CASES, ids=[f"{c['name'][:2]}-{m}" for c, m in CASES]
)
def test_and_v4_vectors(case, matcher):
    found = search_feed(
        ROWS,
        case["arguments"],
        NOW,
        CONTRACT,
        question=case["question"],
        rank="rank_v1",
        matcher=matcher,
    )
    expected = case[matcher]
    ids = [r["id"] for r in found]
    assert ids == expected["expected_ids"]
    terms = question_terms(case["question"])
    got = [
        points(
            terms,
            BY_ID[i]["title"].lower(),
            BY_ID[i]["body"].lower(),
            AND_V3_RULES[matcher],
        )
        for i in ids
    ]
    assert got == expected["expected_points"]


def test_synonyms_v2_is_v1_plus_pasok_only():
    assert {k: v for k, v in SYNONYMS_V2.items() if k != "pasok"} == SYNONYMS
    assert SYNONYMS_V2["pasok"] == ["class"]
    assert "pasok" not in SYNONYMS


def test_the_feed_search_rejects_other_matchers():
    with pytest.raises(ValueError):
        search_feed(ROWS, {"query": "x"}, NOW, CONTRACT, matcher="and_v2")
