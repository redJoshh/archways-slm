"""extract_v1 (v2 fix (d)) against the hand-written vectors, and in flow()."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant import assistant
from archways_assistant.extract import EXTRACT_V1, LABEL, extract
from archways_assistant.past_date import PAST_DATE_V1

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "extract_vectors.json").read_text("utf-8")
)
CASES = DATA["cases"]
PROMPTS = {
    "query": (ROOT / "prompts" / "e2e_query_v1.txt").read_text("utf-8"),
    "answer": (ROOT / "prompts" / "e2e_answer_v1.txt").read_text("utf-8"),
}
QUERY = '{"query": "schedule", "days": 30}'
MODEL_REPLY = "It is on the date in the announcement."


def test_the_vector_file():
    assert DATA["format"] == "archways extract vectors v1"
    assert DATA["rule"] == EXTRACT_V1
    assert DATA["label"] == LABEL
    assert len(CASES) == 30


def run(case, **rules):
    outcome, calls, _ = assistant.flow(
        case["question"],
        datetime.fromisoformat(case["now"]),
        PROMPTS,
        QUERY,
        case["results"],
        150,
        MODEL_REPLY,
        budget="off",
        **rules,
    )
    return outcome, calls


IDS = [c["name"].split(":")[0] for c in CASES]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_extract_steps(case):
    found = extract(case["question"], case["results"])
    assert found.classified is case["classified"]
    words = None if found.words is None else list(found.words)
    assert words == case["words"]
    assert found.admissible is case["admissible"]
    sentences = None if found.sentences is None else list(found.sentences)
    assert sentences == case["sentences"]
    assert found.guard_fired is case["guard_fired"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_extract_in_flow(case):
    outcome, calls = run(case, extract=EXTRACT_V1, past_date=PAST_DATE_V1)
    if case["quote"] is None:
        # The normal path runs, with the model's answer.
        assert outcome.path == "answer"
        assert calls.answer_prompt is not None
        return
    listed = assistant.results_list(case["results"])
    assert outcome.path == "extract"
    assert outcome.text == LABEL + "\n" + case["quote"] + "\n\n" + listed
    assert list(outcome.codes) == case["codes"]
    assert outcome.budget is None
    assert outcome.result_count == len(case["results"])
    # No answer call: only the query prompt was built.
    assert calls.answer_prompt is None


def test_x1_full_text_spelled_out():
    case = CASES[0]
    outcome, _ = run(case, extract=EXTRACT_V1, past_date=PAST_DATE_V1)
    assert outcome.text == (
        "From the announcement below:\n"
        "The deadline for enrollment is December 5, 2026.\n"
        "\n"
        "These announcements may help:\n"
        "- Enrollment for the Second Term (posted November 6, 2026)\n"
        "- Library Hours (posted November 6, 2026)"
    )


def test_off_is_unchanged():
    for case in CASES:
        assert run(case)[0].path == "answer"


def test_without_past_date_the_quote_has_no_note():
    case = next(c for c in CASES if c["name"].startswith("X2:"))
    outcome, _ = run(case, extract=EXTRACT_V1)
    assert "(already passed)" not in outcome.text
    assert outcome.codes == ()


def test_extract_skips_the_count_and_the_answer_reply():
    case = CASES[0]
    outcome, _, _ = assistant.flow(
        case["question"],
        datetime.fromisoformat(case["now"]),
        PROMPTS,
        QUERY,
        case["results"],
        None,
        assistant.ERROR,
        extract=EXTRACT_V1,
    )
    assert outcome.path == "extract"


def test_an_unknown_rule_is_rejected():
    with pytest.raises(ValueError):
        run(CASES[0], extract="extract_v2")
