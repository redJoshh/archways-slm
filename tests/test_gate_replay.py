"""eval_flow.py's gate_v1 replay (accuracy-phase.md (d)) on synthetic records."""

import importlib.util
import json
import sys
from pathlib import Path

from archways_assistant import assistant
from archways_assistant.fakebackend import to_announcement
from archways_assistant.feedindex import feed_row

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
GATE = json.loads((ROOT / "tests" / "vectors" / "gate_vectors.json").read_text("utf-8"))
ROWS = {row["id"]: row for row in (feed_row(d)[0] for d in GATE["details"])}
OFFICES = {row["office"] for row in ROWS.values()}
CL = "Are there classes on November 30, 2026?"
MK = "Kailan ang pasok ng make-up classes?"


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


def case(question, sources):
    return {
        "id": "c",
        "question": question,
        "source_ids": sources,
        "must_include": [],
        "must_not_include": [],
        "expects_not_found": False,
        "data": "seed",
    }


def record(ids, path="answer"):
    results = [to_announcement(ROWS[i]) for i in ids]
    return {"set": "s", "id": "c", "results": results, "path": path, "text": "x"}


def test_the_gate_judges_the_first_result_only():
    module = load()
    c = case(CL, ["3"])
    # Row 4 (0 points) first fails theta 1/4, even though row 3 (7/7) is second.
    out = module.gate_record(c, record(["4", "3"]), ROWS, OFFICES, "and_v3", 1, 4)
    assert out["path"] == "not_about" and out["gated"]
    kept = module.gate_record(c, record(["3", "4"]), ROWS, OFFICES, "and_v3", 1, 4)
    assert kept["path"] == "answer" and "gated" not in kept


def test_the_gate_uses_the_runs_matcher_synonyms():
    module = load()
    c = case(MK, ["7"])
    # Row 7: 3/4 under and_v4 (pasok via class), 2/4 under and_v3.
    assert (
        module.gate_record(c, record(["7"]), ROWS, OFFICES, "and_v4", 3, 4)["path"]
        == "answer"
    )
    assert (
        module.gate_record(c, record(["7"]), ROWS, OFFICES, "and_v3", 3, 4)["path"]
        == "not_about"
    )


def test_not_about_text_and_score_are_the_list_under_the_gates_header():
    module = load()
    c = case(CL, ["3"])
    out = module.gate_record(c, record(["4", "3"]), ROWS, OFFICES, "and_v3", 1, 4)
    listed = assistant.results_list(out["results"])
    assert (
        out["text"] == module.NOT_ABOUT_HEADER + listed[len(assistant.RESULTS_HEADER) :]
    )
    assert out["text"].startswith(
        "I couldn't find an announcement that answers this exactly. These may be related:\n- "
    )
    assert out["score"]["path"] == "not_about"
    assert out["score"]["helpful"] is True  # row 3 is listed
    assert out["score"]["answered"] is False


def test_paths_without_an_answer_call_are_never_gated():
    module = load()
    c = case(CL, ["3"])
    for path in ("not_found", "query_invalid", "search_error"):
        rec = record(["4"], path)
        assert module.gate_record(c, rec, ROWS, OFFICES, "and_v3", 3, 4) is rec


def score(correct, helpful=True):
    return {
        "helpful": helpful,
        "wrong": [],
        "answered": correct,
        "correct": correct,
        "trap": False,
        "out_of_scope": False,
        "clean": None,
        "unrelated_list": False,
        "path": "answer" if correct else "not_about",
    }


def test_correct_case_by_case_catches_a_correct_answer_turned_into_a_list(tmp_path):
    module = load()

    def run(name, scores):
        path = tmp_path / name
        cases = [{"set": "s", "id": i, "score": s} for i, s in scores.items()]
        path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
        return path

    base = run("a.json", {"c1": score(True), "c2": score(True)})
    new = run("b.json", {"c1": score(False, helpful=True), "c2": score(True)})
    # Helpfulness alone can't see it ...
    assert module.nothing_worse(base, new, set())
    # ... the case-by-case AI-correct check does.
    assert not module.nothing_worse(base, new, set(), correct_cases=True)
