"""rank_v1 against the hand-written tests/vectors/rank_vectors.json."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant.feedindex import feed_row, search_feed
from archways_assistant.rank import points, question_terms

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "tests" / "vectors" / "rank_vectors.json").read_text("utf-8"))
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text("utf-8")
)
NOW = datetime.fromisoformat(DATA["now"])
ROWS = [feed_row(detail)[0] for detail in DATA["details"]]
BY_ID = {row["id"]: row for row in ROWS}
CASES = DATA["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:2] for c in CASES])
def test_question_terms(case):
    terms = question_terms(case["question"])
    expected = case["expected_terms"]
    assert list(terms.words) == expected["words"]
    assert sorted(f"{m:02d}-{d:02d}" for m, d in terms.dates) == expected["dates"]
    assert sorted(str(n) for n in terms.numbers) == expected["numbers"]
    assert terms.possible == case["possible"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:2] for c in CASES])
def test_ranked_order_and_points(case):
    found = search_feed(
        ROWS,
        case["arguments"],
        NOW,
        CONTRACT,
        question=case["question"],
        rank="rank_v1",
    )
    assert [r["id"] for r in found] == case["expected_ids"]
    terms = question_terms(case["question"])
    got = [
        points(terms, BY_ID[i]["title"].lower(), BY_ID[i]["body"].lower())
        for i in case["expected_ids"]
    ]
    assert got == case["expected_points"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:2] for c in CASES])
def test_without_rank_the_order_is_newest_first(case):
    found = search_feed(ROWS, case["arguments"], NOW, CONTRACT)
    assert [r["id"] for r in found] == case["unranked_ids"]


def test_rank_needs_the_question_and_and_v3():
    args = {"query": "office", "days": 30}
    with pytest.raises(ValueError):
        search_feed(ROWS, args, NOW, CONTRACT, rank="rank_v1")
    with pytest.raises(ValueError):
        search_feed(ROWS, args, NOW, CONTRACT, question="q", rank="rank_v2")


def test_row_6_has_its_date_past_the_excerpt():
    """Vector C only means something if the date really is past char 500."""
    body = BY_ID["6"]["body"]
    assert body.index("2026-12-05") > 500
