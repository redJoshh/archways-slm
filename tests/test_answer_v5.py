"""answer_v5 (v2 fix (f)): the prompt file and the compact_v5 user message
against the hand-written tests/vectors/answer_v5_vectors.json, and in flow()."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant import assistant

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "answer_v5_vectors.json").read_text("utf-8")
)
CASES = DATA["cases"]
V1 = ROOT / "prompts" / "e2e_answer_v1.txt"
V5 = ROOT / "prompts" / "e2e_answer_v5.txt"


def test_prompt_v5_is_v1_byte_for_byte():
    assert V5.read_bytes() == V1.read_bytes()


def test_the_vector_file():
    assert DATA["format"] == "archways answer_v5 vectors v1"
    assert DATA["rule"] == assistant.COMPACT_V5
    assert len(CASES) == 3


@pytest.mark.parametrize("case", CASES, ids=[c["name"][:2] for c in CASES])
def test_compact_message(case):
    results = assistant.check_results(case["results"])
    got = assistant.compact_answer_user_message(case["question"], results)
    assert got == case["expected"]


PROMPTS = {
    "query": (ROOT / "prompts" / "e2e_query_v1.txt").read_text("utf-8"),
    "answer": V5.read_text("utf-8"),
}


def run(case, **rules):
    return assistant.flow(
        case["question"],
        datetime.fromisoformat("2026-11-19T10:00:00+08:00"),
        PROMPTS,
        '{"query": "enrollment", "days": 30}',
        case["results"],
        150,
        "It opens soon.",
        budget="off",
        **rules,
    )


def test_flow_sends_the_compact_message():
    case = CASES[0]
    outcome, calls, _ = run(case, answer_format=assistant.COMPACT_V5)
    assert case["expected"] in calls.answer_prompt
    assert case["expected"] in calls.answer_case_part
    assert outcome.path == "answer"


def test_flow_default_is_v1_json():
    case = CASES[0]
    _, calls, _ = run(case)
    results = assistant.check_results(case["results"])
    assert (
        assistant.answer_user_message(case["question"], results) in calls.answer_prompt
    )


def test_an_unknown_format_is_rejected():
    with pytest.raises(ValueError):
        run(CASES[0], answer_format="compact_v2")
