"""past_date_v1 (v2 fix (c)) against the hand-written vectors, and in flow().

Every vector also checks that the guard and the scorer read the annotated
text exactly as the original (claims, and the guard's fired and codes).
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant import assistant
from archways_assistant.e2escore import claims, guard
from archways_assistant.past_date import NOTE, PAST_DATE_V1, annotate, result_sources

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "past_date_vectors.json").read_text("utf-8")
)
CASES = DATA["cases"]


def full(result: dict, index: int) -> dict:
    return {
        "id": str(index + 1),
        "title": result["title"],
        "excerpt": result["excerpt"],
        "office": "Test Office",
        "priority": "NORMAL",
        "year_level": None,
        "posted_at": "2026-11-06T09:00:00+08:00",
    }


def test_the_vector_file():
    assert DATA["format"] == "archways past_date vectors v1"
    assert DATA["rule"] == PAST_DATE_V1
    assert DATA["note"] == NOTE
    assert len(CASES) == 22


@pytest.mark.parametrize("case", CASES, ids=[c["name"].split(":")[0] for c in CASES])
def test_past_date_vectors(case):
    now = datetime.fromisoformat(case["now"])
    sources = result_sources(case["results"])
    assert annotate(case["reply"], sources, now) == case["expected"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"].split(":")[0] for c in CASES])
def test_the_guard_and_scorer_read_the_annotated_text_the_same(case):
    results = [full(r, i) for i, r in enumerate(case["results"])]
    original, annotated = case["reply"], case["expected"]
    assert claims(annotated) == claims(original)
    before = guard(original, results, "", [])
    after = guard(annotated, results, "", [])
    assert (after.fired, after.codes) == (before.fired, before.codes)


def test_the_note_has_no_digit_and_no_month():
    found = claims("x" + NOTE)
    assert not found.dates and not found.numbers


NOW = datetime.fromisoformat("2026-11-10T10:00:00+08:00")
PROMPTS = {
    "query": (ROOT / "prompts" / "e2e_query_v1.txt").read_text("utf-8"),
    "answer": (ROOT / "prompts" / "e2e_answer_v1.txt").read_text("utf-8"),
}
RESULT = full(
    {"title": "Misa de Apertura", "excerpt": "The Mass is on August 7, 2026."}, 9
)


def run(reply, past_date):
    outcome, _, _ = assistant.flow(
        "When is the Misa de Apertura?",
        NOW,
        PROMPTS,
        '{"query": "Misa de Apertura", "days": 30}',
        [RESULT],
        150,
        reply,
        budget="off",
        past_date=past_date,
    )
    return outcome


def test_flow_notes_the_answer_but_never_the_list():
    outcome = run("It is held on August 7, 2026.", PAST_DATE_V1)
    listed = assistant.results_list([RESULT])
    assert outcome.path == "answer"
    assert "past_date" in outcome.codes
    answer, _, rest = outcome.text.partition(assistant.ANSWER_LIST_SEPARATOR)
    assert answer.endswith("August 7, 2026 (already passed).")
    assert rest == listed
    assert NOTE not in rest


def test_flow_off_and_nothing_past_are_unchanged():
    off = run("It is held on August 7, 2026.", None)
    assert NOTE not in off.text and "past_date" not in off.codes
    future = run("It is on January 15, 2027.", PAST_DATE_V1)
    assert NOTE not in future.text and "past_date" not in future.codes


def test_an_unknown_rule_is_rejected():
    with pytest.raises(ValueError):
        run("x.", "past_date_v2")
