"""contradiction_v1 (v2 fix (a)) against the hand-written vectors, and in flow()."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant import assistant
from archways_assistant.contradiction import CONTRADICTION_V1, fires, tokens

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "contradiction_vectors.json").read_text("utf-8")
)
CASES = DATA["cases"]


def test_the_vector_file():
    assert DATA["format"] == "archways contradiction vectors v1"
    assert DATA["rule"] == CONTRADICTION_V1
    assert len(CASES) == 20


@pytest.mark.parametrize("case", CASES, ids=[c["name"].split(":")[0] for c in CASES])
def test_contradiction_vectors(case):
    assert fires(case["question"], case["reply"], case["results"]) is case["expected"]


def test_apostrophes_join_only_between_word_characters():
    assert tokens("can't can’t 'quoted' end'") == ["can't", "can't", "quoted", "end"]


NOW = datetime.fromisoformat("2026-11-17T10:00:00+08:00")
PROMPTS = {
    "query": (ROOT / "prompts" / "e2e_query_v1.txt").read_text("utf-8"),
    "answer": (ROOT / "prompts" / "e2e_answer_v1.txt").read_text("utf-8"),
}
RESULT = {
    "id": "29",
    "title": "Dress Code Advisory",
    "excerpt": "Crop tops are strictly prohibited inside the campus.",
    "office": "Office for Student Affairs",
    "priority": "NORMAL",
    "year_level": None,
    "posted_at": "2026-11-06T17:31:05+08:00",
}


def run(reply, contradiction):
    outcome, _, _ = assistant.flow(
        "Can I wear a crop top on a wash day?",
        NOW,
        PROMPTS,
        '{"query": "crop top", "days": 30}',
        [RESULT],
        150,
        reply,
        budget="off",
        contradiction=contradiction,
    )
    return outcome


def test_flow_blocks_with_the_list_and_the_code():
    outcome = run("Yes, you can wear a crop top.", CONTRADICTION_V1)
    assert outcome.path == "guard_fired"
    assert "contradiction" in outcome.codes
    assert outcome.text == assistant.results_list([RESULT])


def test_flow_off_is_unchanged():
    outcome = run("Yes, you can wear a crop top.", None)
    assert outcome.path == "answer"


def test_flow_lets_a_correct_no_through():
    outcome = run("No, crop tops are not allowed.", CONTRADICTION_V1)
    assert outcome.path == "answer"


def test_an_unknown_rule_is_rejected():
    with pytest.raises(ValueError):
        run("Yes.", "contradiction_v2")
