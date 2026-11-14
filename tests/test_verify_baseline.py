"""eval_flow.py: the baseline configuration (the held-out script's path) is pinned.

--verify-baseline re-runs it with the frozen baseline's query replies; these
tests cover the comparison and the part a reuse run skips: the query call.
"""

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

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


def record(**changes) -> dict:
    base = {
        "set": "s",
        "id": "c1",
        "arguments": {"query": "x"},
        "search": ["1"],
        "case_tokens": 100,
        "answer_reply": "A.",
        "path": "answer",
        "text": "T",
        "score": {"helpful": True},
    }
    return {**base, **changes}


def write(tmp_path: Path, cases: list[dict]) -> Path:
    path = tmp_path / "base.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return path


def test_identical_records_verify(tmp_path, capsys):
    module = load()
    assert module.verify_baseline(write(tmp_path, [record()]), [record()])


def test_in_memory_tuples_equal_the_saved_lists(tmp_path, capsys):
    """The first real verify (2026-11-14) failed on this: tuple != list."""
    module = load()
    saved = record(score={"wrong": [], "result_ids": ["1", "2"]})
    fresh = record(score={"wrong": (), "result_ids": ("1", "2")})
    assert module.verify_baseline(write(tmp_path, [saved]), [fresh])


def test_any_difference_fails_and_is_named(tmp_path, capsys):
    module = load()
    base = write(tmp_path, [record()])
    for change in (
        {"text": "U"},
        {"path": "guard_fired"},
        {"score": {"helpful": False}},
        {"search": ["2"]},
        {"answer_reply": "B."},
    ):
        assert not module.verify_baseline(base, [record(**change)])
        field = next(iter(change))
        assert f"c1 ({field})" in capsys.readouterr().out


def test_the_default_path_makes_the_query_call_with_flows_prompt(monkeypatch):
    """The held-out script calls run_case with the defaults: no saved reply."""
    module = load()
    from archways_assistant import assistant

    calls = []

    def fake_generate(client, model, prompt, n_predict):
        calls.append((prompt, n_predict))
        if n_predict == module.QUERY_N_PREDICT:
            return {"response": '{"query": "office", "days": 30}'}
        if n_predict == 1:
            return {"prompt_eval_count": 100}
        return {"response": "The office is open."}

    searched = []

    def fake_search(rows, arguments, now, contract, *, question=None, rank=None):
        searched.append(rank)
        return [
            {
                "id": "1",
                "title": "Office Hours",
                "excerpt": "The office is open.",
                "office": "O",
                "priority": "NORMAL",
                "year_level": None,
                "posted_at": "2026-11-07T09:00:00+08:00",
            }
        ]

    monkeypatch.setattr(module, "generate", fake_generate)
    monkeypatch.setattr(module, "search_feed", fake_search)
    prompts = {
        "query": module.QUERY_PROMPT.read_text(encoding="utf-8"),
        "answer": module.ANSWER_PROMPT.read_text(encoding="utf-8"),
    }
    case = {"question": "When is the office open?"}
    case["now"] = datetime.fromisoformat("2026-11-14T10:00:00+08:00")
    result = module.run_case(None, "m", case, prompts, [], {})
    _, expected, _ = assistant.flow(case["question"], case["now"], prompts, "x")
    assert calls[0] == (expected.query_prompt, module.QUERY_N_PREDICT)
    assert [n for _, n in calls] == [
        module.QUERY_N_PREDICT,
        1,
        assistant.ANSWER_N_PREDICT,
    ]
    assert searched == [None]  # newest first: the baseline configuration
    assert result["path"] == "answer"
