"""scorer_v1 (docs/plans/accuracy-phase.md, section 0) on hand-written replies."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from archways_assistant import assistant
from archways_assistant.e2escore import NOT_FOUND_MESSAGE
from archways_assistant.evalflow import (
    CaseFileError,
    entity_problems,
    load_cases,
    score_case,
    split_final_text,
    totals,
)
from archways_assistant.fakebackend import to_announcement

ROOT = Path(__file__).resolve().parents[1]

ROWS = [
    {
        "id": "r1",
        "title": "Suspension of Office Operations for the Annual Outing",
        "body": "All offices are closed on May 14, 2027 for the outing.",
        "office": "Office of the Secretary-General",
    },
    {
        "id": "r2",
        "title": "Water Interruption Advisory",
        "body": "Water is off on February 25, 2027 until 5:00 PM.",
        "office": "Facilities Management Office",
    },
    {
        "id": "r3",
        "title": "Paskuhan Volunteers",
        "body": "Volunteers meet on December 3, 2026. Coordinate with the Office of the Registrar.",
        "office": "Office for Student Affairs",
    },
]
for row in ROWS:
    row.update(
        priority="NORMAL",
        year_level=None,
        published_at="2026-11-07T09:00:00",
        status="PUBLISHED",
        is_archived=False,
        scheduled=False,
    )
BY_ID = {row["id"]: row for row in ROWS}
OFFICES = {row["office"] for row in ROWS} | {"Office of the Registrar"}


def results(*ids: str) -> list[dict]:
    return [to_announcement(BY_ID[i]) for i in ids]


def answer_text(reply: str, found: list[dict]) -> str:
    return (
        assistant.ANSWER_LABEL
        + assistant.ANSWER_LABEL_SEPARATOR
        + reply
        + assistant.ANSWER_LIST_SEPARATOR
        + assistant.results_list(found)
    )


def case(**fields) -> dict:
    base = {
        "id": "c1",
        "question": "Which office suspended operations for the outing?",
        "source_ids": ["r1"],
        "must_include": [["Secretary-General", "OSG"]],
        "must_not_include": [],
        "expects_not_found": False,
    }
    return {**base, **fields}


def score(c: dict, path: str, text: str, found: list[dict]):
    return score_case(c, path, text, found, BY_ID, OFFICES)


# --- split_final_text -------------------------------------------------------


def test_split_answer_path_gives_the_answer_and_the_list():
    found = results("r1", "r2")
    answer, shown = split_final_text("answer", answer_text("Hi.", found), found)
    assert (answer, shown) == ("Hi.", ["r1", "r2"])


def test_split_list_paths_and_fixed_messages():
    found = results("r2")
    listed = assistant.results_list(found)
    for path in ("answer_not_found", "guard_fired", "budget_fallback", "answer_error"):
        assert split_final_text(path, listed, found) == (None, ["r2"])
    assert split_final_text("not_found", NOT_FOUND_MESSAGE, []) == (None, [])
    last = assistant.LAST_RESORT_MESSAGE
    assert split_final_text("query_error", last, []) == (None, [])


def test_split_rejects_an_answer_without_its_list():
    with pytest.raises(ValueError):
        split_final_text("answer", "just text", results("r1"))
    with pytest.raises(ValueError):
        split_final_text("guard_fired", "other text", results("r1"))


# --- answerable cases -------------------------------------------------------


def test_correct_answer_is_correct_and_helpful():
    found = results("r1", "r2")
    s = score(
        case(),
        "answer",
        answer_text("The Office of the Secretary-General.", found),
        found,
    )
    assert (s.correct, s.helpful, s.unsafe, s.coverage) == (True, True, False, (1, 1))


def test_must_include_is_read_from_the_answer_only_never_the_list():
    found = results("r1")
    c = case(must_include=[["Annual Outing"]])  # in r1's title, so in the list
    s = score(c, "answer", answer_text("Please check the list below.", found), found)
    assert s.missing == ("Annual Outing",)
    assert not s.correct
    # Not wrong, and the source row is listed: still helpful through the list.
    assert s.helpful and not s.unsafe


def test_wrong_entity_is_unsafe_even_with_the_source_listed():
    """The flow q01 failure: the office of an unrelated top result."""
    found = results("r2", "r1")
    reply = "It was published by the Facilities Management Office."
    s = score(case(), "answer", answer_text(reply, found), found)
    assert s.wrong == ("entity:Facilities Management Office",)
    assert s.unsafe and not s.helpful and not s.correct


def test_entity_named_in_a_source_row_text_is_not_wrong():
    rows = [BY_ID["r3"]]
    assert entity_problems("Ask the Office of the Registrar.", OFFICES, rows) == []
    assert entity_problems(
        "Ask the office of the secretary-general.", OFFICES, rows
    ) == ["entity:Office of the Secretary-General"]
    # Whole phrase only.
    assert entity_problems("the Office of the Registrars", OFFICES, []) == []


def test_wrong_row_date_is_unsafe():
    found = results("r1", "r2")
    reply = "The Office of the Secretary-General, on February 25."
    s = score(case(), "answer", answer_text(reply, found), found)
    assert any(code.startswith("wrong_row:r2 date 02-25") for code in s.wrong)
    assert s.unsafe and not s.helpful


def test_must_not_include_and_wrong_claims_are_unsafe():
    found = results("r1")
    c = case(must_not_include=["closed forever"], wrong_claims=["OSA published it"])
    reply = "OSG: closed forever. OSA published it."
    s = score(c, "answer", answer_text(reply, found), found)
    assert s.wrong == ("contains:closed forever", "wrong_claim:OSA published it")


def test_false_not_found_on_an_answerable_case_is_unhelpful():
    s = score(case(), "not_found", NOT_FOUND_MESSAGE, [])
    assert (s.helpful, s.answered, s.unsafe, s.coverage) == (
        False,
        False,
        False,
        (0, 1),
    )


def test_list_path_with_a_source_row_is_helpful():
    found = results("r2", "r1")
    s = score(case(), "answer_not_found", assistant.results_list(found), found)
    assert s.helpful and not s.answered
    assert s.places() == ["r1@2"]


def test_multi_source_any_one_shown_is_helpful_and_coverage_counts():
    found = results("r3", "r2")
    c = case(source_ids=["r1", "r3"])
    s = score(c, "guard_fired", assistant.results_list(found), found)
    assert s.helpful and s.coverage == (1, 2)


# --- traps ------------------------------------------------------------------


def trap(**fields) -> dict:
    return case(source_ids=[], must_include=[], expects_not_found=True, **fields)


def test_trap_not_found_is_clean_without_a_list():
    s = score(trap(), "not_found", NOT_FOUND_MESSAGE, [])
    assert (s.clean, s.unrelated_list, s.helpful) == (True, False, None)


def test_trap_list_path_is_clean_with_an_unrelated_list():
    found = results("r2")
    s = score(trap(), "answer_not_found", assistant.results_list(found), found)
    assert (s.clean, s.unrelated_list, s.unsafe) == (True, True, False)


def test_trap_answer_is_never_clean_or_correct_and_unsafe_only_if_wrong():
    found = results("r2")
    honest = score(trap(), "answer", answer_text("Nothing about that.", found), found)
    assert (honest.clean, honest.correct, honest.unsafe) == (False, False, False)
    wrong = score(trap(), "answer", answer_text("It is on February 25.", found), found)
    assert wrong.unsafe and not wrong.clean


# --- out of scope and totals -------------------------------------------------


def test_out_of_scope_is_scored_on_unsafe_only():
    found = results("r2")
    c = case(out_of_scope=True)
    s = score(c, "answer", answer_text("Facilities Management Office.", found), found)
    assert (s.helpful, s.clean, s.unsafe) == (None, None, True)
    counts = totals([s])
    assert counts["helpful"] == (0, 0)
    assert counts["ai_correct"] == (0, 0)
    assert counts["unsafe"] == (1, 1)
    assert counts["out_of_scope"] == 1


def test_totals_are_counts_over_the_right_denominators():
    a = results("r1", "r2")
    scores = [
        score(case(id="a"), "answer", answer_text("OSG.", a), a),  # correct
        score(
            case(id="b"), "answer", answer_text("Facilities Management Office.", a), a
        ),
        score(case(id="c"), "not_found", NOT_FOUND_MESSAGE, []),
        score(trap(id="t1"), "not_found", NOT_FOUND_MESSAGE, []),
        score(trap(id="t2"), "answer_not_found", assistant.results_list(a), a),
        score(trap(id="t3"), "answer", answer_text("Nothing.", a), a),
    ]
    counts = totals(scores)
    assert counts["helpful"] == (1, 3)
    assert counts["ai_correct"] == (1, 3)
    assert counts["unsafe"] == (1, 6)
    assert counts["traps_clean"] == (2, 3)
    assert counts["traps_unrelated_list"] == (1, 3)
    assert counts["coverage"] == (2, 3)
    assert counts["paths"] == {"answer": 3, "answer_not_found": 1, "not_found": 2}


# --- loader -------------------------------------------------------------------

KNOWN = {"seed": {"r1", "r2", "r3"}, "snapshot": {"18"}}
SECRET = "do-not-print-this-question"


def write(tmp_path: Path, *lines: dict) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path


def good(**fields) -> dict:
    return {**case(question=SECRET), "now": "2026-11-10T10:00:00+08:00", **fields}


def test_loader_reads_now_or_the_fixed_now(tmp_path):
    path = write(tmp_path, good())
    assert load_cases(path, KNOWN)[0]["now"] == datetime.fromisoformat(
        "2026-11-10T10:00:00+08:00"
    )
    fixed = datetime(2026, 11, 14, 2, tzinfo=UTC)
    no_now = {k: v for k, v in good().items() if k != "now"}
    assert load_cases(write(tmp_path, no_now), KNOWN, fixed)[0]["now"] == fixed
    assert load_cases(path, KNOWN, fixed)[0]["now"] == fixed


@pytest.mark.parametrize(
    "bad",
    [
        {"source_ids": ["nope"]},
        {"data": "elsewhere"},
        {"must_include": [[]]},
        {"must_include": [SECRET]},
        {"now": SECRET},
        {"surprise": SECRET},
        {"source_ids": [], "expects_not_found": False},
        {"wrong_rows": [SECRET]},
    ],
)
def test_loader_errors_never_print_a_value(tmp_path, bad):
    with pytest.raises(CaseFileError) as error:
        load_cases(write(tmp_path, good(**bad)), KNOWN)
    assert SECRET not in str(error.value)
    assert "line 1" in str(error.value)


def test_loader_rejects_duplicate_ids_and_bad_json(tmp_path):
    with pytest.raises(CaseFileError):
        load_cases(write(tmp_path, good(), good()), KNOWN)
    path = tmp_path / "bad.jsonl"
    path.write_text("{" + SECRET + "\n", encoding="utf-8")
    with pytest.raises(CaseFileError) as error:
        load_cases(path, KNOWN)
    assert SECRET not in str(error.value)


def test_the_dev_case_files_load():
    seed = json.loads(
        (ROOT / "data" / "seed" / "announcements.json").read_text("utf-8")
    )
    known = {"seed": {row["id"] for row in seed}, "snapshot": set()}
    e2e = load_cases(ROOT / "evals" / "e2e_cases.jsonl", known)
    taglish = load_cases(ROOT / "evals" / "taglish_cases.jsonl", known)
    assert (len(e2e), len(taglish)) == (34, 10)


# scorer_v1 is frozen (accuracy-phase.md, 2026-11-14): this file's bytes are
# pinned, line endings normalised to LF. A change to a rule is scorer_v2 in a
# new dated plan section, with the dev sets re-scored from saved run files;
# the held-out baseline can't be re-scored.
SCORER_V1_SHA256 = "44cd630851a30cf28d76d26e4e416ac92708c21b2ce0e4c6236d4de8b7174691"


def test_scorer_v1_is_frozen():
    data = (ROOT / "src" / "archways_assistant" / "evalflow.py").read_bytes()
    digest = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    assert digest == SCORER_V1_SHA256, "scorer_v1 is frozen; a change is scorer_v2"
