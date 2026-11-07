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
            vector["elapsed_ms"],
            speed_of(vector["speed"]),
        )
        expected = vector["expected"]
        budget = outcome.budget
        assert expected["budget"] == (
            None
            if budget is None
            else {
                "rule": budget.rule,
                "fallback": budget.fallback,
                "predicted_ms": budget.predicted_ms,
            }
        ), vector["id"]
        assert outcome.result_count == expected["result_count"], vector["id"]
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
                assert expected["text"].startswith(
                    reply.strip(assistant.ASCII_WHITESPACE)
                    + assistant.ANSWER_LIST_SEPARATOR
                    + assistant.RESULTS_HEADER
                    + "\n- "
                ), vector["id"]
            else:
                assert reply.strip() not in expected["text"], vector["id"]


def test_every_path_with_results_ends_with_the_results_list():
    """ADR 0004 UAT configuration (2026-11-07)."""
    seen = set()
    for vector in DATA["flow"]:
        expected = vector["expected"]
        if not expected["result_count"]:
            assert assistant.RESULTS_HEADER not in expected["text"], vector["id"]
            continue
        listed = assistant.results_list(vector["search_reply"])
        assert expected["text"].endswith(listed), vector["id"]
        assert listed.count("\n- ") == expected["result_count"], vector["id"]
        if expected["path"] != "answer":
            assert expected["text"] == listed, vector["id"]
        seen.add(expected["path"])
    assert seen == {
        "answer",
        "answer_not_found",
        "guard_fired",
        "budget_fallback",
        "answer_error",
    }


def test_answer_not_found_needs_the_exact_sentence():
    by_id = {vector["id"]: vector["expected"] for vector in DATA["flow"]}
    for id_ in (
        "answer-not-found-sentence",
        "answer-not-found-trimmed",
        "time-answer-not-found",
    ):
        assert by_id[id_]["path"] == "answer_not_found", id_
        assert assistant.NOT_FOUND_MESSAGE not in by_id[id_]["text"], id_
    for id_ in (
        "answer-not-found-lowercase",
        "answer-not-found-plus-text",
        "answer-not-found-nbsp",
    ):
        assert by_id[id_]["path"] == "answer", id_
    # No results: the not-found message, no list, no answer call.
    assert by_id["not-found"]["text"] == assistant.NOT_FOUND_MESSAGE


def test_results_list_rejects_a_changed_fallback_header(monkeypatch):
    monkeypatch.setattr(assistant, "fallback", lambda results: "Other:\n- x")
    with pytest.raises(ValueError):
        assistant.results_list([])


def speed_of(value) -> assistant.Speed | None:
    return None if value is None else assistant.Speed(**value)


def test_budget_boundary():
    by_id = {vector["id"]: vector["expected"] for vector in DATA["flow"]}
    assert assistant.BUDGET_CASE_TOKENS == 200
    assert by_id["answer-at-budget"]["path"] == "answer"
    assert by_id["budget-over-by-one"]["path"] == "budget_fallback"
    assert by_id["budget-e2e-009"]["path"] == "budget_fallback"
    assert by_id["budget-e2e-009"]["budget"]["rule"] == "tokens"


def test_time_budget_boundary_and_replay():
    by_id = {vector["id"]: vector["expected"] for vector in DATA["flow"]}
    assert assistant.BAR_MS == 15000
    assert by_id["time-at-bar"]["budget"] == {
        "rule": "time",
        "fallback": False,
        "predicted_ms": 15000.0,
    }
    assert by_id["time-at-bar"]["path"] == "answer"
    assert by_id["time-over-bar"]["path"] == "budget_fallback"
    # The 2026-10-31 Redmi runs: e2e-009 measured 20.2 s, e2e-004 11.9 s.
    assert by_id["time-redmi-e2e-009"]["path"] == "budget_fallback"
    assert by_id["time-redmi-e2e-009"]["budget"]["predicted_ms"] > 18000
    assert by_id["time-redmi-e2e-004"]["path"] == "answer"
    assert by_id["time-redmi-e2e-004"]["budget"]["predicted_ms"] < 15000
    # A faster phone answers e2e-009, which the tokens rule never would.
    assert by_id["time-fast-e2e-009"]["path"] == "answer"
    assert by_id["tokens-partial-speed"]["path"] == "budget_fallback"
    assert by_id["tokens-partial-at-budget"]["path"] == "answer"
    assert by_id["n-ctx-at-limit"]["path"] == "answer"
    assert by_id["n-ctx-over"]["budget"] == {
        "rule": "n_ctx",
        "fallback": True,
        "predicted_ms": None,
    }
    assert assistant.GEN_TOKENS > 0


def test_speed_vectors_reproduce():
    assert len(DATA["speed"]) >= 20
    for vector in DATA["speed"]:
        got = assistant.update_speed(speed_of(vector["speed"]), vector["timings"])
        assert speed_of(vector["expected"]) == got, vector["id"]


def pending_of(value) -> assistant.Pending:
    return assistant.Pending(value["n"], value["ms"])


def test_answer_speed_vectors_reproduce():
    assert len(DATA["answer_speed"]) >= 20
    for vector in DATA["answer_speed"]:
        speed, pending = speed_of(vector["speed"]), pending_of(vector["pending"])
        assert len(vector["steps"]) == len(vector["expected"])
        for timings, expected in zip(vector["steps"], vector["expected"], strict=True):
            speed, pending = assistant.update_answer_speed(speed, pending, timings)
            assert speed == speed_of(expected["speed"]), vector["id"]
            assert pending == pending_of(expected["pending"]), vector["id"]


def test_redmi_not_found_replies_make_the_speed_known():
    """Redmi 2026-11-07: three 8-token not-found replies, no priming."""
    by_id = {vector["id"]: vector for vector in DATA["answer_speed"]}
    steps = by_id["redmi-not-found-x3"]["expected"]
    assert steps[0]["speed"]["gen_tps"] is None
    assert 12.7 < steps[1]["speed"]["gen_tps"] < 12.8
    assert steps[1]["pending"] == {"n": 0, "ms": 0.0}
    # update_speed() alone (priming) never adds short replies up.
    short = by_id["redmi-not-found-x3"]["steps"][0]
    assert assistant.update_speed(None, short).gen_tps is None


@pytest.mark.parametrize("ms", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_predicted_ms_is_ignored(ms):
    timings = {"predicted_n": 8, "predicted_ms": ms, "predicted_per_second": 12.8}
    pending = assistant.Pending(8, 600.0)
    assert assistant.update_answer_speed(None, pending, timings) == (
        assistant.Speed(),
        pending,
    )


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_rates_are_ignored(rate):
    # Not expressible in JSON vectors; the TS tests repeat this.
    speed = assistant.Speed(28.0, 10.4)
    timings = {
        "prompt_n": 200,
        "prompt_per_second": rate,
        "predicted_n": 20,
        "predicted_per_second": rate,
    }
    assert assistant.update_speed(speed, timings) == speed


def test_query_and_answer_prompts_start_with_their_own_prefixes():
    now = datetime.fromisoformat("2026-11-06T10:00:00+08:00")
    for name in ("e2e_query_v1.txt", "e2e_answer_v1.txt"):
        template = (ROOT / "prompts" / name).read_text(encoding="utf-8")
        system = assistant.fill_prompt(template, now)
        prefix = assistant.system_turn(system)
        assert prefix == f"<|im_start|>system\n\n{system}<|im_end|>\n"
        assert "Today is Friday, 2026-11-06 (Asia/Manila)." in prefix
