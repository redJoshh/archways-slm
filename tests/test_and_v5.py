"""and_v5 (with rank_v1) against the hand-written tests/vectors/and_v5_vectors.json,
and the frozen synonyms v3 file (v2 fix (e), the Taglish lexicon v1)."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant.fakebackend import AND_V3_RULES, SYNONYMS_V2, SYNONYMS_V3
from archways_assistant.feedindex import feed_row, search_feed
from archways_assistant.rank import points, question_terms

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "and_v5_vectors.json").read_text("utf-8")
)
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text("utf-8")
)
V3 = ROOT / "contracts" / "search_synonyms_v3.json"
NOW = datetime.fromisoformat(DATA["now"])
ROWS = [feed_row(detail)[0] for detail in DATA["details"]]
BY_ID = {row["id"]: row for row in ROWS}
CASES = [(c, m) for c in DATA["cases"] for m in ("and_v5", "and_v4")]


def test_the_frozen_map():
    assert hashlib.sha256(V3.read_bytes()).hexdigest() == DATA["synonyms_sha256"]
    assert AND_V3_RULES["and_v5"] is SYNONYMS_V3
    # v3 = v2 + 98 lexicon terms; every v2 entry is unchanged.
    assert {k: SYNONYMS_V3[k] for k in SYNONYMS_V2} == SYNONYMS_V2
    assert len(SYNONYMS_V3) - len(SYNONYMS_V2) == 98


@pytest.mark.parametrize(
    ("case", "matcher"), CASES, ids=[f"{c['name'][:3]}-{m}" for c, m in CASES]
)
def test_and_v5_vectors(case, matcher):
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
    got_points = [
        points(
            terms,
            BY_ID[i]["title"].lower(),
            BY_ID[i]["body"].lower(),
            AND_V3_RULES[matcher],
        )
        for i in ids
    ]
    assert got_points == expected["expected_points"]
