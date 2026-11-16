"""Fix (g) strip_nf_v1 (accuracy-phase.md): the stray not-found sentence.

Checked against the hand-written tests/vectors/strip_nf_vectors.json, which
was committed before any code or run.
"""

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant import assistant
from archways_assistant.e2escore import NOT_FOUND_MESSAGE

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VECTORS = json.loads(
    (ROOT / "tests" / "vectors" / "strip_nf_vectors.json").read_text(encoding="utf-8")
)
PROMPTS = {
    "query": (ROOT / "prompts" / "e2e_query_v1.txt").read_text(encoding="utf-8"),
    "answer": (ROOT / "prompts" / "e2e_answer_v1.txt").read_text(encoding="utf-8"),
}
NOW = datetime.fromisoformat("2026-11-02T10:00:00+08:00")
ROW = {
    "id": "1",
    "title": "Second Term",
    "excerpt": "The Second Term starts on January 15, 2027.",
    "office": "Office of the Registrar",
    "priority": "NORMAL",
    "year_level": None,
    "posted_at": "2026-11-01T09:00:00+08:00",
}
QUERY = '{"query": "second term"}'
QUESTION = "When does the second term start?"


def test_vector_file_is_the_registered_one():
    assert VECTORS["format"] == "archways strip_nf vectors v1"
    assert VECTORS["rule"] == assistant.STRIP_NF_V1
    assert VECTORS["not_found"] == NOT_FOUND_MESSAGE
    assert len(VECTORS["cases"]) == 9


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_strip_nf_v1_vectors(case):
    got = assistant.answer_reply_text(case["reply"], assistant.STRIP_NF_V1)
    assert got == case["expected"]


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_off_is_the_uat_rule(case):
    # Off: only the ASCII strip and the exact-sentence check, as before (g).
    stripped = case["reply"].strip(assistant.ASCII_WHITESPACE)
    expected = None if stripped == NOT_FOUND_MESSAGE else stripped
    assert assistant.answer_reply_text(case["reply"]) == expected


def test_unknown_rule_is_refused():
    with pytest.raises(ValueError):
        assistant.answer_reply_text("x", "strip_nf_v2")
    with pytest.raises(ValueError):
        assistant.flow(QUESTION, NOW, PROMPTS, QUERY, [ROW], 100, "x", strip_nf="v2")


def run(reply: str, strip_nf: str | None):
    outcome, _, _ = assistant.flow(
        QUESTION,
        NOW,
        PROMPTS,
        QUERY,
        [ROW],
        100,
        reply,
        budget="off",
        strip_nf=strip_nf,
    )
    return outcome


def test_flow_answer_then_sentence_shows_only_the_answer():
    reply = f"The Second Term starts on January 15, 2027. {NOT_FOUND_MESSAGE}"
    outcome = run(reply, assistant.STRIP_NF_V1)
    assert outcome.path == "answer"
    assert NOT_FOUND_MESSAGE not in outcome.text
    assert outcome.text.startswith(
        assistant.ANSWER_LABEL
        + assistant.ANSWER_LABEL_SEPARATOR
        + "The Second Term starts on January 15, 2027."
        + assistant.ANSWER_LIST_SEPARATOR
    )
    # Off: the reply reaches the guard with the sentence, as in the UAT flow.
    assert NOT_FOUND_MESSAGE in run(reply, None).text


def test_flow_sentence_twice_is_answer_not_found():
    reply = f"{NOT_FOUND_MESSAGE} {NOT_FOUND_MESSAGE}"
    outcome = run(reply, assistant.STRIP_NF_V1)
    assert outcome.path == "answer_not_found"
    assert outcome.text == assistant.results_list([ROW])
    assert run(reply, None).path != "answer_not_found"


def test_flow_default_is_off():
    reply = f"The Second Term starts on January 15, 2027. {NOT_FOUND_MESSAGE}"
    outcome, _, _ = assistant.flow(
        QUESTION, NOW, PROMPTS, QUERY, [ROW], 100, reply, budget="off"
    )
    assert outcome == run(reply, None)


def load_eval_flow():
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


def test_run_case_passes_strip_nf_to_the_final_flow(monkeypatch):
    module = load_eval_flow()
    reply = f"The Second Term starts on January 15, 2027. {NOT_FOUND_MESSAGE}"

    def fake_generate(client, model, prompt, n_predict):
        if n_predict == 1:
            return {"prompt_eval_count": 100}
        return {"response": reply}

    monkeypatch.setattr(module, "generate", fake_generate)
    monkeypatch.setattr(module, "search_feed", lambda *a, **k: [ROW])
    case = {"question": QUESTION, "now": NOW}
    on = module.run_case(
        None, "m", case, PROMPTS, [], {}, query_reply=QUERY, strip_nf="strip_nf_v1"
    )
    off = module.run_case(None, "m", case, PROMPTS, [], {}, query_reply=QUERY)
    assert on["answer_reply"] == off["answer_reply"] == reply
    assert NOT_FOUND_MESSAGE not in on["text"]
    assert NOT_FOUND_MESSAGE in off["text"]


def test_verify_baseline_refuses_strip_nf(monkeypatch, tmp_path):
    module = load_eval_flow()
    argv = [
        "eval_flow.py",
        "--out",
        str(ROOT / "data" / "local" / "runs" / "never-written.json"),
        "--verify-baseline",
        str(tmp_path / "base.json"),
        "--strip-nf",
        "strip_nf_v1",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as raised:
        module.main()
    assert raised.value.code == 2
