"""retry_v1 against the hand-written tests/vectors/retry_vectors.json."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant.fakebackend import InvalidArguments
from archways_assistant.feedindex import feed_row, search_feed_retry

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "retry_vectors.json").read_text("utf-8")
)
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text("utf-8")
)
NOW = datetime.fromisoformat(DATA["now"])
ROWS = [feed_row(detail)[0] for detail in DATA["details"]]
CASES = DATA["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:2] for c in CASES])
def test_retry_vectors(case):
    if not case["ok"]:
        with pytest.raises(InvalidArguments):
            search_feed_retry(
                ROWS, case["arguments"], NOW, CONTRACT, question=case["question"]
            )
        return
    results, retried = search_feed_retry(
        ROWS, case["arguments"], NOW, CONTRACT, question=case["question"]
    )
    assert [r["id"] for r in results] == case["expected_ids"]
    assert retried == case["retried"]


def test_retry_off_is_the_plain_ranked_search():
    case = CASES[0]  # R1: zero results without the retry
    results, retried = search_feed_retry(
        ROWS, case["arguments"], NOW, CONTRACT, question=case["question"], retry=None
    )
    assert (results, retried) == ([], False)


def test_an_unknown_retry_version_is_rejected():
    with pytest.raises(ValueError):
        search_feed_retry(
            ROWS, {"query": "x"}, NOW, CONTRACT, question="q", retry="retry_v2"
        )
