"""excerpt_v2_centred against the hand-derived tests/vectors/window_vectors.json."""

import json
from pathlib import Path

import pytest

from archways_assistant.window import anchor, centred_excerpt

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "window_vectors.json").read_text("utf-8")
)
CASES = DATA["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:4] for c in CASES])
def test_window_vectors(case):
    args = (case["body"], case["question"], case["query"], case["matcher"])
    got = centred_excerpt(*args)
    assert got == case["expected"]
    assert len(got) <= 500
    if case["anchor"] is not None and len(case["body"].lower()) == len(case["body"]):
        assert list(anchor(*args)) == case["anchor"]


def test_window_through_the_search():
    from datetime import datetime

    from archways_assistant.feedindex import feed_row, search_feed

    s = DATA["search"]
    contract = json.loads(
        (ROOT / "contracts" / "search_announcements.schema.json").read_text("utf-8")
    )
    rows = [feed_row(detail)[0] for detail in s["details"]]
    found = search_feed(
        rows,
        s["arguments"],
        datetime.fromisoformat(s["now"]),
        contract,
        question=s["question"],
        rank=s["rank"],
        matcher=s["matcher"],
        excerpt="excerpt_v2_centred",
    )
    assert [r["id"] for r in found] == s["expected_ids"]
    assert [r["excerpt"] for r in found] == s["expected_excerpts"]
