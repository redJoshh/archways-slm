"""eval_flow.score_outcome: an extract is scored by scorer_v1 exactly as an answer
(v2-improvements.md, extract_v1 rule, "Scoring"; user decision 7.3)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from archways_assistant import assistant
from archways_assistant.evalflow import score_case
from archways_assistant.extract import LABEL

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "eval_flow", SCRIPTS / "eval_flow.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


EF = load()
ROW = {
    "id": "70",
    "title": "Enrollment for the Second Term",
    "body": "The deadline for enrollment is December 5, 2026.",
    "office": "Office of the Registrar",
}
RESULT = {
    "id": "70",
    "title": ROW["title"],
    "excerpt": ROW["body"],
    "office": ROW["office"],
    "priority": "NORMAL",
    "year_level": None,
    "posted_at": "2026-11-06T09:00:00+08:00",
}
QUOTE = "The deadline for enrollment is December 5, 2026."
LISTED = assistant.results_list([RESULT])


def case(**over):
    base = {
        "id": "x",
        "question": "When is the enrollment deadline?",
        "expects_not_found": False,
        "source_ids": ["70"],
        "must_include": [["December 5"]],
        "must_not_include": [],
        "wrong_claims": [],
        "wrong_rows": [],
        "data": "snapshot",
    }
    base.update(over)
    return base


def texts(quote=QUOTE):
    extract = LABEL + "\n" + quote + "\n\n" + LISTED
    answer = assistant.ANSWER_LABEL + "\n" + quote + "\n\n" + LISTED
    return extract, answer


@pytest.mark.parametrize(
    "over",
    [
        {},
        {"must_include": [["December 6"]]},
        {"must_not_include": ["December 5"]},
        {"expects_not_found": True, "source_ids": []},
    ],
    ids=["correct", "not-correct", "wrong", "trap"],
)
def test_an_extract_scores_exactly_as_the_same_answer(over):
    c = case(**over)
    extract, answer = texts()
    rows = {"70": ROW}
    got = EF.score_outcome(c, "extract", extract, [RESULT], rows, {ROW["office"]})
    want = score_case(c, "answer", answer, [RESULT], rows, {ROW["office"]})
    assert got.path == "extract"
    assert {**got.__dict__, "path": "answer"} == want.__dict__


def test_a_trap_extract_is_never_clean_or_correct():
    c = case(expects_not_found=True, source_ids=[])
    got = EF.score_outcome(c, "extract", texts()[0], [RESULT], {"70": ROW}, set())
    assert got.answered and not got.clean and not got.correct


def test_other_paths_are_scored_unchanged():
    c = case()
    rows = {"70": ROW}
    got = EF.score_outcome(c, "answer_not_found", LISTED, [RESULT], rows, set())
    assert got == score_case(c, "answer_not_found", LISTED, [RESULT], rows, set())


def test_the_extract_line():
    c = case()
    rows = {"70": ROW}
    good = EF.score_outcome(c, "extract", texts()[0], [RESULT], rows, set())
    bad = EF.score_outcome(
        case(must_include=[["x"]]), "extract", texts()[0], [RESULT], rows, set()
    )
    line = EF.format_extract("flow13", [good, bad])
    assert "extract correct 1/2" in line
    assert "answer correct (AI + extract)" in line
    assert EF.format_extract("flow13", []) is None


def test_an_extract_text_without_its_label_is_refused():
    with pytest.raises(ValueError):
        EF.score_outcome(case(), "extract", LISTED, [RESULT], {"70": ROW}, set())
