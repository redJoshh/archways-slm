"""The assistant reference (UAT flow) against the probe, the contract and its vectors."""

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from archways_assistant import assistant
from archways_assistant.render import render_qwen3

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VECTORS = ROOT / "tests" / "vectors" / "assistant_vectors.json"
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text(
        encoding="utf-8"
    )
)
DATA = json.loads(VECTORS.read_text(encoding="utf-8"))

# Query texts where the spec (ECMA-262 "\S", well-formed Unicode) and
# Python's jsonschema (Python re "\S") disagree. Documented gaps.
ARGUMENT_SPEC_GAPS = {
    '{"query": "\\u0085"}',  # Python re: whitespace; ECMA-262: not
    '{"query": "\\u001c"}',  # Python re: whitespace; ECMA-262: not
    '{"query": "\\ufeff"}',  # ECMA-262: whitespace; Python re: not
    '{"query": "\\ud800"}',  # the spec rejects lone surrogates
}


def load_script(name: str):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def from_ms(ms: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)


def test_vector_file_is_up_to_date():
    exporter = load_script("export_assistant_vectors")
    assert exporter.build() == VECTORS.read_text(encoding="utf-8")


def test_generated_ts_is_up_to_date():
    exporter = load_script("export_assistant_ts")
    assert exporter.render() == exporter.OUT.read_text(encoding="utf-8")


def test_vector_file_is_ascii_and_lf():
    raw = VECTORS.read_bytes()
    assert raw.isascii()
    assert b"\r\n" not in raw


def test_vector_counts():
    assert len(DATA["render"]) >= 44
    assert {v["expected"]["path"] for v in DATA["flow"]} == set(assistant.PATHS)


def test_contract_bounds_match_the_reference():
    arguments = CONTRACT["$defs"]["arguments"]["properties"]
    announcement = CONTRACT["$defs"]["announcement"]
    assert tuple(announcement["required"]) == assistant.KEYS
    check = assistant.check_arguments
    for key, prop in (("days", arguments["days"]), ("limit", arguments["limit"])):
        low, high = prop["minimum"], prop["maximum"]
        check({"query": "x", key: low})
        check({"query": "x", key: high})
        for bad in (low - 1, high + 1):
            with pytest.raises(assistant.ContractError):
                check({"query": "x", key: bad})
    check({"query": "a" * arguments["query"]["maxLength"]})
    with pytest.raises(assistant.ContractError):
        check({"query": "a" * (arguments["query"]["maxLength"] + 1)})


def test_today_matches_strftime_in_manila():
    for vector in DATA["today"]:
        local = from_ms(vector["now_ms"]).astimezone(assistant.MANILA)
        assert vector["today"] == f"{local:%A}, {local:%Y-%m-%d}"


def test_render_vectors_equal_what_the_probe_sends():
    probe = load_script("probe_end_to_end")
    for vector in DATA["render"]:
        now = from_ms(vector["now_ms"])
        question, results = vector["question"], vector["results"]
        query_system = probe.load_prompt(probe.QUERY_PROMPT, now, None)
        answer_system = probe.load_prompt(probe.ANSWER_PROMPT, now, None)
        # The reference serializes in the contract's key order whatever order
        # the rows arrive in; the probe keeps the order it is given.
        canonical = assistant.check_results(results)
        answer_user = probe.announcements_message(question, canonical)
        if not vector["id"].startswith("edge-"):
            assert canonical == results, vector["id"]
        assert vector["answer_user"] == answer_user, vector["id"]
        assert vector["query_prompt"] == render_qwen3(
            [
                {"role": "system", "content": query_system},
                {"role": "user", "content": question},
            ]
        )
        assert vector["answer_prompt"] == render_qwen3(
            [
                {"role": "system", "content": answer_system},
                {"role": "user", "content": answer_user},
            ]
        )
        assert vector["query_prompt"].startswith(vector["query_prefix"])
        assert (
            vector["answer_prefix"] + vector["answer_case_part"]
            == (vector["answer_prompt"])
        )
        assert vector["answer_prefix"].endswith("<|im_end|>\n")
        assert vector["answer_case_part"].startswith("<|im_start|>user\n")


def test_results_json_equals_json_dumps():
    for vector in DATA["render"]:
        rows = assistant.check_results(vector["results"])
        assert assistant.results_json(rows) == json.dumps(
            rows, ensure_ascii=False, indent=1
        )


def test_argument_check_agrees_with_the_contract_outside_documented_gaps():
    validator = Draft202012Validator(CONTRACT["$defs"]["arguments"])
    seen_gaps = set()
    for vector in DATA["query"]:
        text = vector["text"]
        try:
            value = json.loads(text, parse_constant=assistant.reject_constant)
        except ValueError:
            assert not vector["ok"], text
            continue
        contract_ok = validator.is_valid(value)
        if text in ARGUMENT_SPEC_GAPS:
            seen_gaps.add(text)
            assert vector["ok"] != contract_ok, text
        else:
            assert vector["ok"] == contract_ok, text
    assert seen_gaps == ARGUMENT_SPEC_GAPS


def test_results_check_never_accepts_what_the_contract_rejects():
    validator = Draft202012Validator(
        {**CONTRACT["$defs"]["result"], "$defs": CONTRACT["$defs"]},
    )
    for vector in DATA["results"]:
        if vector["ok"]:
            assert validator.is_valid(vector["value"]), vector["value"]


def test_flow_vectors_reproduce():
    prompts = {
        "query": (ROOT / "prompts" / "e2e_query_v1.txt").read_text(encoding="utf-8"),
        "answer": (ROOT / "prompts" / "e2e_answer_v1.txt").read_text(encoding="utf-8"),
    }

    def decode(value):
        return assistant.ERROR if value == {"throws": True} else value

    for vector in DATA["flow"]:
        outcome, calls, arguments = assistant.flow(
            vector["question"],
            from_ms(vector["now_ms"]),
            prompts,
            decode(vector["query_reply"]),
            decode(vector["search_reply"]),
            decode(vector["case_tokens"]),
            decode(vector["answer_reply"]),
        )
        expected = vector["expected"]
        assert outcome.path == expected["path"], vector["id"]
        assert outcome.text == expected["text"], vector["id"]
        assert list(outcome.codes) == expected["codes"], vector["id"]
        assert arguments == expected["arguments"], vector["id"]
        assert (calls.query_prompt if calls else None) == expected["query_prompt"]
        assert (calls.answer_prompt if calls else None) == expected["answer_prompt"]


def test_flow_shows_model_text_only_on_the_answer_path():
    for vector in DATA["flow"]:
        expected = vector["expected"]
        reply = vector["answer_reply"]
        if isinstance(reply, str) and reply.strip(assistant.ASCII_WHITESPACE):
            if expected["path"] == "answer":
                assert expected["text"] == reply.strip(assistant.ASCII_WHITESPACE)
            else:
                assert reply.strip() not in expected["text"], vector["id"]


def test_budget_boundary():
    by_id = {vector["id"]: vector["expected"]["path"] for vector in DATA["flow"]}
    assert assistant.BUDGET_CASE_TOKENS == 200
    assert by_id["answer-at-budget"] == "answer"
    assert by_id["budget-over-by-one"] == "budget_fallback"
    assert by_id["budget-e2e-009"] == "budget_fallback"


def test_query_and_answer_prompts_start_with_their_own_prefixes():
    now = datetime.fromisoformat("2026-11-06T10:00:00+08:00")
    for name in ("e2e_query_v1.txt", "e2e_answer_v1.txt"):
        template = (ROOT / "prompts" / name).read_text(encoding="utf-8")
        system = assistant.fill_prompt(template, now)
        prefix = assistant.system_turn(system)
        assert prefix == f"<|im_start|>system\n\n{system}<|im_end|>\n"
        assert "Today is Friday, 2026-11-06 (Asia/Manila)." in prefix
