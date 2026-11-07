"""Write tests/vectors/assistant_vectors.json from archways_assistant.assistant.

Usage: uv run python scripts/export_assistant_vectors.py [--check]

The vectors define what assistant-ts must do, case by case:
- today: the Manila weekday and date for instants around midnight
- render: the query and answer prompts, prefixes and case parts for every
  e2e and Taglish dev case at its own now. The results are the seed rows
  named in the case (or the first two visible rows for a case with none),
  so the messages look like real ones. No model is called.
- query: query replies and whether they are valid search arguments
- results: search replies and whether they meet the result contract
- flow: whole questions with every step scripted, and the outcome
- speed: update_speed() (priming and answer calls)
- answer_speed: update_answer_speed() over a sequence of answer calls,
  with the running total of short replies

Expected values come from the Python reference only. --check exits 1 if the
committed file differs. Deterministic: no clock, no network, no model.
The output is ASCII-only JSON with LF line endings.
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from archways_assistant import assistant
from archways_assistant.assistant import (
    ERROR,
    Pending,
    Speed,
    flow,
    update_answer_speed,
    update_speed,
)
from archways_assistant.fakebackend import is_visible, to_announcement

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "vectors" / "assistant_vectors.json"
SEED = ROOT / "data" / "seed" / "announcements.json"
CASE_FILES = (
    ROOT / "evals" / "e2e_cases.jsonl",
    ROOT / "evals" / "taglish_cases.jsonl",
)
PROMPTS = {
    "query": (ROOT / "prompts" / "e2e_query_v1.txt").read_text(encoding="utf-8"),
    "answer": (ROOT / "prompts" / "e2e_answer_v1.txt").read_text(encoding="utf-8"),
}
THROWS = {"throws": True}


def to_ms(now: datetime) -> int:
    delta = now - datetime(1970, 1, 1, tzinfo=UTC)
    return delta // timedelta(milliseconds=1)


def from_ms(ms: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)


def load_cases() -> list[dict]:
    cases = []
    for path in CASE_FILES:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                case = json.loads(line)
                cases.append({**case, "_file": path.name})
    return cases


def case_results(case: dict, rows: list[dict], now: datetime) -> list[dict]:
    by_id = {row["id"]: row for row in rows}
    ids = case.get("source_ids") or []
    chosen = [by_id[id_] for id_ in ids if id_ in by_id]
    if not chosen:
        chosen = [row for row in rows if is_visible(row, now)][:2]
    results = [to_announcement(row) for row in chosen]
    return sorted(results, key=lambda r: r["posted_at"], reverse=True)


def today_vectors() -> list[dict]:
    instants = [
        "2026-11-05T15:59:59.999+00:00",  # 23:59:59.999 Manila, Thursday
        "2026-11-05T16:00:00+00:00",  # 00:00 Manila, Friday
        "2026-11-06T08:30:00+08:00",
        "2026-11-08T23:59:00+08:00",  # Sunday
        "2026-11-09T00:00:00+08:00",  # Monday
        "2026-12-31T16:00:00+00:00",  # 2027-01-01 Manila
        "2028-02-28T16:00:00+00:00",  # 2028-02-29 Manila, leap day
        "2026-11-02T10:00:00-05:00",  # 23:00 Manila
    ]
    out = []
    for text in instants:
        now = datetime.fromisoformat(text)
        out.append({"now_ms": to_ms(now), "today": assistant.today_text(now)})
    return out


def render_vectors(rows: list[dict]) -> list[dict]:
    out = []
    for case in load_cases():
        now = datetime.fromisoformat(case["now"])
        question = case["question"]
        results = case_results(case, rows, now)
        query_system = assistant.fill_prompt(PROMPTS["query"], now)
        answer_system = assistant.fill_prompt(PROMPTS["answer"], now)
        user = assistant.answer_user_message(question, results)
        _, calls, _ = flow(question, now, PROMPTS, '{"query": "x"}', results, 0, "")
        out.append(
            {
                "id": case["id"],
                "now_ms": to_ms(now),
                "question": question,
                "results": results,
                "query_prefix": assistant.system_turn(query_system),
                "query_prompt": calls.query_prompt,
                "answer_prefix": assistant.system_turn(answer_system),
                "answer_user": user,
                "answer_case_part": calls.answer_case_part,
                "answer_prompt": calls.answer_prompt,
            }
        )
    return out


EDGE_ROW = {
    "id": "edge-1",
    "title": 'Tab\there "quoted" \\ back <b>bold</b>',
    "excerpt": "Line one\nline two\r\n\u0001\u001f\u007f \u2028\u2029 \u00e9\u00f1 \U0001f600 caf\u00e9",
    "office": "Office of <Student> Affairs",
    "priority": "high",
    "year_level": 2,
    "posted_at": "2026-11-05T09:00:00+08:00",
}


def edge_render_vectors() -> list[dict]:
    now = datetime.fromisoformat("2026-11-06T10:00:00+08:00")
    plain = {**EDGE_ROW, "id": "edge-2", "year_level": None, "title": "Plain"}
    reordered = dict(reversed(list({**EDGE_ROW, "id": "edge-3"}.items())))
    cases = [
        ("edge-escapes", "When is it?", [EDGE_ROW]),
        ("edge-null-year-and-order", "Ano ang <b>?", [EDGE_ROW, plain, reordered]),
        ("edge-ten-rows", "Ten", [{**plain, "id": f"r-{i}"} for i in range(10)]),
    ]
    out = []
    for id_, question, results in cases:
        query_system = assistant.fill_prompt(PROMPTS["query"], now)
        answer_system = assistant.fill_prompt(PROMPTS["answer"], now)
        _, calls, _ = flow(question, now, PROMPTS, '{"query": "x"}', results, 0, "")
        out.append(
            {
                "id": id_,
                "now_ms": to_ms(now),
                "question": question,
                "results": results,
                "query_prefix": assistant.system_turn(query_system),
                "query_prompt": calls.query_prompt,
                "answer_prefix": assistant.system_turn(answer_system),
                "answer_user": assistant.answer_user_message(
                    question, assistant.check_results(results)
                ),
                "answer_case_part": calls.answer_case_part,
                "answer_prompt": calls.answer_prompt,
            }
        )
    return out


QUERY_REPLIES = [
    '{"query": "student portal", "days": 30}',
    '{"query": "curriculum advising session", "days": 30}',
    '{"query": "x"}',
    '  {"query": "x", "limit": 3}\n',
    '{"query": "x", "days": 30.0}',
    '{"query": "x", "days": 3e1}',
    '{"query": "x", "days": 1E1}',
    '{"query": "x", "days": 1.5}',
    '{"query": "x", "days": 0}',
    '{"query": "x", "days": 31}',
    '{"query": "x", "days": -0}',
    '{"query": "x", "days": "7"}',
    '{"query": "x", "days": true}',
    '{"query": "x", "days": null}',
    '{"query": "x", "days": 1e400}',
    '{"query": "x", "limit": 10}',
    '{"query": "x", "limit": 11}',
    '{"query": "x", "days": 30000000000000000001}',
    '{"query": "x", "page": 2}',
    '{"days": 7}',
    '{"query": ""}',
    '{"query": " "}',
    '{"query": "\\u00a0\\u3000"}',
    '{"query": "\\ufeff"}',
    '{"query": "\\u0085"}',
    '{"query": "\\u001c"}',
    '{"query": "\\ud800"}',
    '{"query": "' + "a" * 200 + '"}',
    '{"query": "' + "a" * 201 + '"}',
    '{"query": "' + "\U0001f600" * 200 + '"}',
    '{"query": "' + "\U0001f600" * 201 + '"}',
    '{"query": "a", "query": "b"}',
    '{"query": 5}',
    '["query"]',
    '"student portal"',
    "null",
    "",
    "student portal",
    '```json\n{"query": "x"}\n```',
    '{"query": "x"} extra',
    '{"query": "x", "days": NaN}',
    '{"query": "x", "days": Infinity}',
    '\ufeff{"query": "x"}',
    '\u00a0{"query": "x"}',
    '{"query": "line\nbreak"}',
    "{'query': 'x'}",
    '{"query": "x",}',
]


def query_vectors() -> list[dict]:
    out = []
    for text in QUERY_REPLIES:
        try:
            arguments = assistant.parse_query_reply(text)
            out.append({"text": text, "ok": True, "arguments": arguments})
        except assistant.ContractError:
            out.append({"text": text, "ok": False, "arguments": None})
    return out


def results_vectors(rows: list[dict]) -> list[dict]:
    good = to_announcement(rows[0])
    values = [
        [],
        [good],
        [EDGE_ROW],
        [{**good, "year_level": 2.0}],
        [{**good, "year_level": -0.0}],
        [{**good, "year_level": 2.5}],
        [{**good, "year_level": True}],
        [{**good, "year_level": "2"}],
        [{**good, "year_level": 2**53}],
        [{**good, "title": "t" * 255}],
        [{**good, "title": "t" * 256}],
        [{**good, "excerpt": "e" * 500}],
        [{**good, "excerpt": "e" * 501}],
        [{**good, "excerpt": "\U0001f600" * 500}],
        [{**good, "posted_at": "2026-11-05 09:00:00"}],
        [{**good, "posted_at": "2026-11-05T09:00:00"}],
        [{**good, "posted_at": "2026-11-05T09:00:00Z"}],
        [{**good, "id": 7}],
        [{**good, "office": None}],
        [{**good, "extra": 1}],
        [{key: value for key, value in good.items() if key != "priority"}],
        [{**good, "title": "\ud800"}],
        [good] * 10,
        [good] * 11,
        [good, "x"],
        {"results": [good]},
        None,
        "[]",
    ]
    out = []
    for value in values:
        try:
            checked = assistant.check_results(value)
            out.append({"value": value, "ok": True, "rows": checked})
        except assistant.ContractError:
            out.append({"value": value, "ok": False, "rows": None})
    return out


def flow_vectors(rows: list[dict]) -> list[dict]:
    by_id = {row["id"]: to_announcement(row) for row in rows}
    now = datetime.fromisoformat("2026-11-02T10:00:00+08:00")
    e2e_009 = [by_id["ann-015"], by_id["ann-001"], by_id["ann-025"]]
    e2e_004 = [by_id["ann-005"]]
    q009 = "When will the student portal be unavailable?"
    q004 = "When is the curriculum advising session for second year students?"
    reply_004 = (
        "Curriculum advising session for second year students is scheduled on "
        "November 10, 2026, from 1:00 PM to 3:00 PM in their college function room."
    )
    reply_009 = (
        "The student portal will be unavailable on November 7, 2026, from 10:00 PM "
        "until 2:00 AM the next day for maintenance."
    )
    invented = "The student portal is unavailable from November 7th to 8th."
    query_009 = '{"query": "student portal", "days": 30}'
    query_004 = '{"query": "curriculum advising session", "days": 30}'
    bad_row = [{**by_id["ann-005"], "posted_at": "yesterday"}]
    not_found = assistant.NOT_FOUND_MESSAGE
    scripts = [
        ("answer", q004, query_004, e2e_004, 177, reply_004),
        ("answer-trimmed", q004, query_004, e2e_004, 177, "\n  " + reply_004 + " \t"),
        # Only ASCII whitespace is trimmed: the NBSP and U+2028 stay.
        (
            "answer-unicode-edges",
            q004,
            query_004,
            e2e_004,
            177,
            "\u00a0" + reply_004 + "\u2028",
        ),
        ("answer-at-budget", q009, query_009, e2e_009, 200, reply_009),
        ("budget-over-by-one", q009, query_009, e2e_009, 201, reply_009),
        ("budget-e2e-009", q009, query_009, e2e_009, 394, reply_009),
        ("guard-fired-invented", q009, query_009, e2e_009, 150, invented),
        ("guard-fired-non-ascii-digit", q004, query_004, e2e_004, 177, "Room \u0661."),
        # The not-found sentence although results exist (Redmi 2026-11-07):
        # the list only. Exact match after the ASCII trim.
        ("answer-not-found-sentence", q004, query_004, e2e_004, 177, not_found),
        (
            "answer-not-found-trimmed",
            q009,
            query_009,
            e2e_009,
            150,
            "\n " + not_found + " \t",
        ),
        # Not exact: these are ordinary replies, guarded, then the list.
        (
            "answer-not-found-lowercase",
            q004,
            query_004,
            e2e_004,
            177,
            not_found.lower(),
        ),
        (
            "answer-not-found-plus-text",
            q004,
            query_004,
            e2e_004,
            177,
            not_found + " Please check with your college.",
        ),
        (
            "answer-not-found-nbsp",
            q004,
            query_004,
            e2e_004,
            177,
            not_found + "\u00a0",
        ),
        ("not-found", q004, '{"query": "swimming pool"}', [], None, None),
        ("query-invalid-prose", q004, "Sure! Searching now.", None, None, None),
        ("query-invalid-fence", q004, '```json\n{"query": "x"}\n```', None, None, None),
        ("query-invalid-days", q004, '{"query": "x", "days": 0}', None, None, None),
        ("query-error", q004, ERROR, None, None, None),
        ("search-error", q004, query_004, ERROR, None, None),
        ("search-contract-broken", q004, query_004, bad_row, None, None),
        ("search-not-an-array", q004, query_004, {"results": e2e_004}, None, None),
        ("count-error", q004, query_004, e2e_004, ERROR, None),
        ("count-not-integer", q004, query_004, e2e_004, 177.5, None),
        ("answer-error", q004, query_004, e2e_004, 177, ERROR),
        ("question-empty", "", None, None, None, None),
        ("question-whitespace", " \t\u3000", None, None, None, None),
        ("question-too-long", "a" * 501, None, None, None, None),
        ("question-at-limit", "a" * 500, query_004, [], None, None),
        (
            "days-normalized",
            q004,
            '{"query": "advising", "days": 30.0}',
            [],
            None,
            None,
        ),
    ]
    # The adaptive time budget: (id, question, query, search, tokens, answer,
    # elapsed_ms, speed). REDMI is the 2026-10-31 phone run's rates.
    redmi = Speed(28.0, 10.4)
    fast = Speed(60.0, 20.0)
    gen = float(assistant.GEN_TOKENS)  # GEN_TOKENS * 1000 / gen = 1000 exactly
    timed = [
        ("time-redmi-e2e-004", q004, query_004, e2e_004, 177, reply_004, 2200, redmi),
        ("time-redmi-e2e-009", q009, query_009, e2e_009, 394, reply_009, 2200, redmi),
        ("time-fast-e2e-009", q009, query_009, e2e_009, 394, reply_009, 2200, fast),
        # 200 * 1000 / 20 = 10000; 3500 + 200 + 10000 + 1000 + 300 = 15000.
        (
            "time-at-bar",
            q009,
            query_009,
            e2e_009,
            200,
            reply_009,
            3500,
            Speed(20.0, gen),
        ),
        (
            "time-over-bar",
            q009,
            query_009,
            e2e_009,
            200,
            reply_009,
            3501,
            Speed(20.0, gen),
        ),
        ("time-error", q009, query_009, e2e_009, 394, ERROR, 2200, fast),
        ("time-guard-fired", q009, query_009, e2e_009, 394, invented, 2200, fast),
        (
            "time-answer-not-found",
            q009,
            query_009,
            e2e_009,
            394,
            assistant.NOT_FOUND_MESSAGE,
            2200,
            fast,
        ),
        # Only one rate known: the tokens rule decides.
        (
            "tokens-partial-speed",
            q009,
            query_009,
            e2e_009,
            201,
            reply_009,
            0,
            Speed(60.0),
        ),
        (
            "tokens-partial-at-budget",
            q009,
            query_009,
            e2e_009,
            200,
            reply_009,
            0,
            Speed(None, 20.0),
        ),
        # n_ctx guard, whatever the speed.
        (
            "n-ctx-at-limit",
            q009,
            query_009,
            e2e_009,
            assistant.CASE_TOKENS_CTX_MAX,
            reply_009,
            0,
            Speed(1000.0, 1000.0),
        ),
        (
            "n-ctx-over",
            q009,
            query_009,
            e2e_009,
            assistant.CASE_TOKENS_CTX_MAX + 1,
            reply_009,
            0,
            Speed(1000.0, 1000.0),
        ),
    ]
    scripts = [(*script, 0, None) for script in scripts] + timed

    def encode(value):
        return THROWS if value is ERROR else value

    out = []
    for id_, question, query, search, tokens, answer, elapsed, speed in scripts:
        outcome, calls, arguments = flow(
            question, now, PROMPTS, query, search, tokens, answer, elapsed, speed
        )
        budget = outcome.budget
        out.append(
            {
                "id": id_,
                "now_ms": to_ms(now),
                "question": question,
                "query_reply": encode(query),
                "search_reply": encode(search),
                "case_tokens": encode(tokens),
                "answer_reply": encode(answer),
                "elapsed_ms": elapsed,
                "speed": speed_json(speed),
                "expected": {
                    "path": outcome.path,
                    "text": outcome.text,
                    "codes": list(outcome.codes),
                    "budget": None
                    if budget is None
                    else {
                        "rule": budget.rule,
                        "fallback": budget.fallback,
                        "predicted_ms": budget.predicted_ms,
                    },
                    "result_count": outcome.result_count,
                    "arguments": arguments,
                    "query_prompt": calls.query_prompt if calls else None,
                    "answer_case_part": calls.answer_case_part if calls else None,
                    "answer_prompt": calls.answer_prompt if calls else None,
                },
            }
        )
    return out


def speed_json(speed: Speed | None) -> dict | None:
    if speed is None:
        return None
    return {"prompt_tps": speed.prompt_tps, "gen_tps": speed.gen_tps}


def speed_vectors() -> list[dict]:
    """update_speed(): (id, previous speed, timings)."""
    redmi = Speed(28.0, 10.4)
    priming = {
        "prompt_n": 213,
        "prompt_per_second": 27.7,
        "predicted_n": 16,
        "predicted_per_second": 10.1,
    }
    cases = [
        ("priming-from-unknown", None, priming),
        ("no-timings", redmi, None),
        ("no-timings-unknown", None, None),
        ("not-an-object", redmi, [1, 2]),
        ("empty-object", redmi, {}),
        ("prompt-n-below", redmi, {**priming, "prompt_n": 99}),
        ("prompt-n-at-min", redmi, {**priming, "prompt_n": 100}),
        ("predicted-n-below", redmi, {**priming, "predicted_n": 9}),
        ("predicted-n-at-min", redmi, {**priming, "predicted_n": 10}),
        ("rate-below-min", redmi, {**priming, "prompt_per_second": 0.99}),
        ("rate-at-min", redmi, {**priming, "prompt_per_second": 1}),
        ("rate-at-max", redmi, {**priming, "predicted_per_second": 1000}),
        ("rate-above-max", redmi, {**priming, "predicted_per_second": 1000.5}),
        ("rate-zero", redmi, {**priming, "prompt_per_second": 0}),
        ("rate-negative", redmi, {**priming, "predicted_per_second": -5}),
        ("rate-string", redmi, {**priming, "prompt_per_second": "27.7"}),
        ("rate-bool", redmi, {**priming, "predicted_per_second": True}),
        ("rate-null", redmi, {**priming, "prompt_per_second": None}),
        ("count-string", redmi, {**priming, "prompt_n": "213"}),
        ("count-bool", redmi, {**priming, "predicted_n": True}),
        ("partial-prompt-only", None, {"prompt_n": 394, "prompt_per_second": 21.9}),
        ("partial-gen-only", None, {"predicted_n": 37, "predicted_per_second": 10.4}),
        (
            "answer-call-short-reply",
            redmi,
            {
                "prompt_n": 177,
                "prompt_per_second": 25.0,
                "predicted_n": 8,
                "predicted_per_second": 14.0,
            },
        ),
    ]
    return [
        {
            "id": id_,
            "speed": speed_json(previous),
            "timings": timings,
            "expected": speed_json(update_speed(previous, timings)),
        }
        for id_, previous, timings in cases
    ]


def answer_timings(predicted_n, predicted_ms, **extra) -> dict:
    """An answer call's timings (prompt rate accepted: 177 tokens)."""
    timings = {
        "prompt_n": 177,
        "prompt_per_second": 25.0,
        "predicted_n": predicted_n,
        "predicted_ms": predicted_ms,
        "predicted_per_second": (
            predicted_n * 1000 / predicted_ms
            if isinstance(predicted_n, int | float)
            and not isinstance(predicted_n, bool)
            and isinstance(predicted_ms, int | float)
            and not isinstance(predicted_ms, bool)
            and predicted_ms > 0
            else 12.8
        ),
    }
    return {**timings, **extra}


def answer_speed_vectors() -> list[dict]:
    """update_answer_speed(): (id, start speed, start pending, timings list).

    The Redmi 2026-11-07 flow test: three not-found replies of 8 tokens at
    12.8, 12.7 and 12.7 tokens/s (625, 630 and 630 ms here).
    """
    redmi = Speed(28.0, 10.4)
    short = answer_timings(8, 625.0)
    cases = [
        (
            "redmi-not-found-x3",
            None,
            Pending(),
            [short, answer_timings(8, 630.0), answer_timings(8, 630.0)],
        ),
        ("short-then-long", None, Pending(), [short, answer_timings(37, 3557.7)]),
        ("long-resets-pending", redmi, Pending(8, 600.0), [answer_timings(37, 3557.7)]),
        (
            "exactly-ten",
            None,
            Pending(),
            [answer_timings(4, 300.0), answer_timings(6, 500.0)],
        ),
        ("nine-is-pending", None, Pending(), [answer_timings(9, 700.0)]),
        ("count-integral-float", None, Pending(), [answer_timings(8.0, 625.0), short]),
        ("count-fraction", None, Pending(), [answer_timings(8.5, 625.0)]),
        ("count-zero", None, Pending(), [answer_timings(0, 625.0)]),
        ("count-bool", None, Pending(), [answer_timings(True, 625.0)]),
        ("count-string", None, Pending(), [answer_timings("8", 625.0)]),
        ("ms-missing", None, Pending(), [{**short, "predicted_ms": None}]),
        (
            "ms-absent",
            None,
            Pending(),
            [{k: v for k, v in short.items() if k != "predicted_ms"}],
        ),
        ("ms-zero", None, Pending(), [answer_timings(8, 0)]),
        ("ms-negative", None, Pending(), [answer_timings(8, -5.0)]),
        ("ms-string", None, Pending(), [answer_timings(8, "625")]),
        ("ms-bool", None, Pending(), [answer_timings(8, True)]),
        # The pooled rate is checked like any rate: 10 tokens in 5 ms is
        # 2000 tokens/s, over RATE_MAX, so it is dropped and pending resets.
        ("pooled-rate-above-max", None, Pending(5, 2.5), [answer_timings(5, 2.5)]),
        (
            "pooled-rate-below-min",
            None,
            Pending(5, 6000.0),
            [answer_timings(5, 5000.0)],
        ),
        # A long reply whose rate is rejected leaves pending as it is.
        (
            "long-rejected-keeps-pending",
            redmi,
            Pending(8, 600.0),
            [answer_timings(20, 1000.0, predicted_per_second=1000.5)],
        ),
        ("not-an-object", redmi, Pending(8, 600.0), [[1, 2]]),
        ("no-timings", redmi, Pending(8, 600.0), [None]),
        ("known-speed-short-replies", redmi, Pending(), [short, short]),
    ]
    out = []
    for id_, speed, pending, steps in cases:
        expected = []
        current, total = speed, pending
        for timings in steps:
            current, total = update_answer_speed(current, total, timings)
            expected.append(
                {"speed": speed_json(current), "pending": pending_json(total)}
            )
        out.append(
            {
                "id": id_,
                "speed": speed_json(speed),
                "pending": pending_json(pending),
                "steps": steps,
                "expected": expected,
            }
        )
    return out


def pending_json(pending: Pending) -> dict:
    return {"n": pending.n, "ms": pending.ms}


def build() -> str:
    rows = json.loads(SEED.read_text(encoding="utf-8"))
    for row in rows:
        row.setdefault("year_level", None)
    data = {
        "format": "archways assistant vectors v1",
        "generator": "scripts/export_assistant_vectors.py",
        "constants": {
            "budget_case_tokens": assistant.BUDGET_CASE_TOKENS,
            "bar_ms": assistant.BAR_MS,
            "gen_tokens": assistant.GEN_TOKENS,
            "case_tokens_ctx_max": assistant.CASE_TOKENS_CTX_MAX,
            "question_max_chars": assistant.QUESTION_MAX_CHARS,
            "paths": list(assistant.PATHS),
        },
        "today": today_vectors(),
        "render": render_vectors(rows) + edge_render_vectors(),
        "query": query_vectors(),
        "results": results_vectors(rows),
        "flow": flow_vectors(rows),
        "speed": speed_vectors(),
        "answer_speed": answer_speed_vectors(),
    }
    return json.dumps(data, ensure_ascii=True, indent=1) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else None
        if current != text:
            sys.exit(f"{OUT.relative_to(ROOT)} is out of date; rerun the script")
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return
    OUT.write_bytes(text.encode("ascii"))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text):,} bytes)")


if __name__ == "__main__":
    main()
