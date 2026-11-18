"""echo_v1 (v2 fix (b)) against the hand-written vectors, and in flow()."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant import assistant
from archways_assistant.contradiction import CONTRADICTION_V1
from archways_assistant.echo import ECHO_V1, is_echo

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "tests" / "vectors" / "echo_vectors.json").read_text("utf-8"))
CASES = DATA["cases"]


def test_the_vector_file():
    assert DATA["format"] == "archways echo vectors v1"
    assert DATA["rule"] == ECHO_V1
    assert len(CASES) == 14


@pytest.mark.parametrize("case", CASES, ids=[c["name"].split(":")[0] for c in CASES])
def test_echo_vectors(case):
    assert is_echo(case["question"], case["reply"]) is case["expected"]


NOW = datetime.fromisoformat("2026-11-17T10:00:00+08:00")
PROMPTS = {
    "query": (ROOT / "prompts" / "e2e_query_v1.txt").read_text("utf-8"),
    "answer": (ROOT / "prompts" / "e2e_answer_v1.txt").read_text("utf-8"),
}
RESULT = {
    "id": "56",
    "title": "Campus Plastic Ban",
    "excerpt": "The ban covers straws, stirrers and plastic bags. Crop tops are prohibited.",
    "office": "Facilities Management Office",
    "priority": "NORMAL",
    "year_level": None,
    "posted_at": "2026-11-07T15:31:47+08:00",
}


def run(question, reply, **rules):
    outcome, _, _ = assistant.flow(
        question,
        NOW,
        PROMPTS,
        '{"query": "plastic ban", "days": 30}',
        [RESULT],
        150,
        reply,
        budget="off",
        **rules,
    )
    return outcome


def test_flow_echo_is_answer_not_found_with_the_list_and_the_code():
    q = "Which items are included in the campus ban on plastics?"
    outcome = run(q, "The campus ban on plastics includes items.", echo=ECHO_V1)
    assert outcome.path == "answer_not_found"
    assert "echo" in outcome.codes
    assert outcome.text == assistant.results_list([RESULT])


def test_flow_off_and_a_real_answer_are_unchanged():
    q = "Which items are included in the campus ban on plastics?"
    echo = "The campus ban on plastics includes items."
    assert run(q, echo).path == "answer"
    answer = "It covers straws, stirrers and plastic bags."
    assert run(q, answer, echo=ECHO_V1).path == "answer"


def test_contradiction_runs_before_echo():
    q = "Can I wear a crop top?"
    outcome = run(q, "Yes.", contradiction=CONTRADICTION_V1, echo=ECHO_V1)
    assert outcome.path == "guard_fired"
    assert "contradiction" in outcome.codes


def test_an_unknown_rule_is_rejected():
    with pytest.raises(ValueError):
        run("q?", "r.", echo="echo_v2")
