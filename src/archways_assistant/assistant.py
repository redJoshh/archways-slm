"""Reference for the on-device assistant flow, the spec that assistant-ts ports.

This is the UAT configuration of ADR 0004: untuned qwen3:0.6b, query prompt
v1, answer prompt v1, the guard, and the budget fallback. The probe
(scripts/probe_end_to_end.py) is not changed and does not use this module.
tests/test_assistant.py checks that the prompts built here equal the
probe's, so what the phone sends is what was evaluated.

Everything here is an explicit spec, not either language's incidental
semantics:

- Today is the Asia/Manila date, a fixed UTC+08:00 (Manila has no DST), with
  fixed English weekday names.
- The answer call's results are serialized as JSON with indent 1, in the
  contract's key order (KEYS), with the escapes of json_string(), then "<"
  becomes \\u003c, exactly as the probe's announcements_message() does for
  contract-valid results.
- The query reply is parsed as strict JSON (no NaN or Infinity) and checked
  against the contract's arguments schema by hand (check_arguments()):
  lengths in code points, "\\S" in the ECMA-262 sense (JSON Schema patterns
  are ECMA-262), integers as JSON numbers with an integral value.
- Results are checked against the contract's result schema
  (check_results()). A result the contract rejects never reaches the model.
- The reply is trimmed of ASCII whitespace only, then guarded.

flow() takes the model's replies, the search results and the token count
as scripted inputs, so it is pure and deterministic.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from archways_assistant.e2escore import (
    FALLBACK_HEADER,
    LAST_RESORT_MESSAGE,
    NOT_FOUND_MESSAGE,
    fallback,
    guard,
    posted_date,
)
from archways_assistant.render import render_qwen3

MANILA = timezone(timedelta(hours=8))
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
TODAY_PLACEHOLDER = "{today}"

# ADR 0004, UAT configuration: an answer call's case part over this many Qwen
# tokens gets the no-model fallback instead of a model call. Since
# 2026-11-06 this is the rule only while the phone's speed is unknown (the
# "tokens" rule); with a known speed the time rule below decides.
BUDGET_CASE_TOKENS = 200

# The adaptive time budget (ADR 0004, UAT configuration). A UAT product
# setting, not a Gate 1 bar: Gate 1 is still measured on the Redmi 10C.
BAR_MS = 15000
# Answer session load, measured 0.1-0.2 s on the Redmi 10C (2026-10-31).
ANSWER_LOAD_MS = 200
# Guard and rendering after the answer call. Proposal, not measured.
OVERHEAD_MS = 300
# Generated answer tokens: the nearest-rank 90th percentile of eval_count over
# every answer call of the e2e and Taglish dev cases with the UAT prompts
# (scripts/measure_reply_tokens.py, 2026-11-06, Ollama 0.40.14: 29 answer
# calls, min 10, median 26, p90 51, max 53; devlog). Phone replies: 37, 41.
GEN_TOKENS = 51
# n_ctx guard: the prompt plus the answer's n_predict must fit n_ctx. The two
# v1 system turns measured 197 and 213 tokens; 300 bounds them.
N_CTX = 2048
ANSWER_N_PREDICT = 200
SYSTEM_TOKENS_MAX = 300
CASE_TOKENS_CTX_MAX = N_CTX - ANSWER_N_PREDICT - SYSTEM_TOKENS_MAX
# A measured rate is used only if it is a finite number in this range
# (tokens/s) and came from enough tokens.
RATE_MIN = 1
RATE_MAX = 1000
PROMPT_N_MIN = 100
# Answer replies shorter than this add up (update_answer_speed()) until
# their total reaches it.
PREDICTED_N_MIN = 10
# Questions longer than this (code points) are refused before any call, so
# a pasted text can't overflow n_ctx 2048. Proposal, not measured.
QUESTION_MAX_CHARS = 500

# The contract's result key order (fakebackend.to_announcement()).
KEYS = ("id", "title", "excerpt", "office", "priority", "year_level", "posted_at")
STRING_KEYS = ("id", "title", "excerpt", "office", "priority", "posted_at")

# ECMA-262 WhiteSpace and LineTerminator: what "\s" matches in a JSON Schema
# pattern. Python's re differs (it adds U+001C-U+001F and U+0085 and drops
# U+FEFF), so this is spelled out.
ECMA_WHITESPACE = frozenset(
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
ASCII_WHITESPACE = " \t\n\r\f\v"

# ADR 0004, UAT configuration (2026-11-07): every path with results ends
# with the results list under this header; a guarded answer goes above it.
RESULTS_HEADER = "These announcements may help:"
# Between the guarded answer and the results list.
ANSWER_LIST_SEPARATOR = "\n\n"

PATHS = (
    "answer",  # the guard passed the reply: the reply, then the results list
    "answer_not_found",  # the reply was the not-found sentence: the list only
    "guard_fired",  # the guard rejected the reply: the list only
    "budget_fallback",  # over budget, no answer call: the list only
    "answer_error",  # counting, the answer call or the guard failed: the list
    "not_found",  # valid search, no results: no answer call
    "query_invalid",  # the query reply is not valid arguments
    "query_error",  # the query call failed
    "search_error",  # the search failed or broke the contract
    "question_invalid",  # empty, whitespace-only or too long
)


class ContractError(ValueError):
    pass


def manila(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now must have a time zone")
    return now.astimezone(MANILA)


def today_text(now: datetime) -> str:
    """The weekday and Manila date of now, e.g. Monday, 2026-11-02."""
    local = manila(now)
    return f"{WEEKDAYS[local.weekday()]}, {local.date().isoformat()}"


def fill_prompt(template: str, now: datetime) -> str:
    """A prompt file's text without its final newline, {today} filled."""
    if TODAY_PLACEHOLDER not in template:
        raise ValueError("prompt has no {today} placeholder")
    return template.removesuffix("\n").replace(TODAY_PLACEHOLDER, today_text(now))


def system_turn(system: str) -> str:
    """The cacheable prefix: everything before the user turn."""
    return render_qwen3(
        [{"role": "system", "content": system}, {"role": "user", "content": ""}]
    ).split("<|im_start|>user\n", 1)[0]


def case_part(system: str, user: str) -> str:
    """The rest of the prompt after system_turn(): the uncached part."""
    prompt = render_qwen3(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
    prefix = system_turn(system)
    assert prompt.startswith(prefix)
    return prompt[len(prefix) :]


def has_lone_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in text)


def json_string(text: str) -> str:
    """json.dumps(text, ensure_ascii=False) for text without lone surrogates.

    Escapes: \\" \\\\ \\b \\f \\n \\r \\t, other characters below U+0020 as
    \\u00xx (lowercase hex). Everything else, including U+007F, U+2028 and
    U+2029, is kept as is.
    """
    out = ['"']
    named = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f"}
    named.update({"\n": "\\n", "\r": "\\r", "\t": "\\t"})
    for char in text:
        if char in named:
            out.append(named[char])
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def results_json(results: list[dict]) -> str:
    """json.dumps(results, ensure_ascii=False, indent=1) in KEYS order."""
    items = []
    for result in results:
        fields = []
        for key in KEYS:
            value = result[key]
            shown = (
                "null"
                if value is None
                else (str(value) if key == "year_level" else json_string(value))
            )
            fields.append(f'  "{key}": {shown}')
        items.append(" {\n" + ",\n".join(fields) + "\n }")
    return "[\n" + ",\n".join(items) + "\n]"


def answer_user_message(question: str, results: list[dict]) -> str:
    data = results_json(results).replace("<", "\\u003c")
    return f"Question: {question}\n\n<announcements>\n{data}\n</announcements>"


def code_points(text: str) -> int:
    return len(text)


def is_integral(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value) and value.is_integer()


def reject_constant(name: str):
    raise ValueError(f"not JSON: {name}")


def parse_query_reply(text: str) -> dict:
    """The search arguments in a query reply, or ContractError.

    Strict JSON for the whole reply; JSON whitespace around it is allowed.
    Integral numbers are returned as int.
    """
    try:
        value = json.loads(text, parse_constant=reject_constant)
    except ValueError as error:
        raise ContractError(f"invalid JSON: {error}") from None
    return check_arguments(value)


def check_arguments(value) -> dict:
    """$defs/arguments of contracts/search_announcements.schema.json."""
    if not isinstance(value, dict):
        raise ContractError("not an object")
    extra = sorted(set(value) - {"query", "days", "limit"})
    if extra:
        raise ContractError(f"unknown key(s): {', '.join(extra)}")
    if "query" not in value:
        raise ContractError("missing query")
    query = value["query"]
    if not isinstance(query, str):
        raise ContractError("query is not a string")
    if has_lone_surrogate(query):
        raise ContractError("query has a lone surrogate")
    if not 1 <= code_points(query) <= 200:
        raise ContractError("query length out of range")
    if all(char in ECMA_WHITESPACE for char in query):
        raise ContractError("query has no non-whitespace character")
    arguments = {"query": query}
    for key, low, high in (("days", 1, 30), ("limit", 1, 10)):
        if key not in value:
            continue
        number = value[key]
        if not is_integral(number):
            raise ContractError(f"{key} is not an integer")
        if not low <= number <= high:
            raise ContractError(f"{key} out of range")
        arguments[key] = int(number)
    return arguments


def check_results(value) -> list[dict]:
    """$defs/result, plus no lone surrogates. Returns the rows in KEYS order."""
    if not isinstance(value, list):
        raise ContractError("results are not an array")
    if len(value) > 10:
        raise ContractError("more than 10 results")
    rows = []
    for index, item in enumerate(value):
        where = f"result {index}"
        if not isinstance(item, dict):
            raise ContractError(f"{where} is not an object")
        if set(item) != set(KEYS):
            raise ContractError(f"{where} keys differ from the contract")
        for key in STRING_KEYS:
            if not isinstance(item[key], str):
                raise ContractError(f"{where} {key} is not a string")
            if has_lone_surrogate(item[key]):
                raise ContractError(f"{where} {key} has a lone surrogate")
        if code_points(item["title"]) > 255:
            raise ContractError(f"{where} title too long")
        if code_points(item["excerpt"]) > 500:
            raise ContractError(f"{where} excerpt too long")
        year = item["year_level"]
        if year is not None and not is_integral(year):
            raise ContractError(f"{where} year_level is not an integer or null")
        if year is not None and not -(2**53) < year < 2**53:
            raise ContractError(f"{where} year_level out of range")
        try:
            posted_date(item["posted_at"])
        except ValueError:
            raise ContractError(f"{where} posted_at is not RFC 3339") from None
        row = {key: item[key] for key in KEYS}
        if year is not None:
            row["year_level"] = int(year)
        rows.append(row)
    return rows


def check_question(question) -> None:
    if not isinstance(question, str) or has_lone_surrogate(question):
        raise ContractError("question is not text")
    if all(char in ECMA_WHITESPACE for char in question):
        raise ContractError("empty question")
    if code_points(question) > QUESTION_MAX_CHARS:
        raise ContractError("question too long")


def is_count(value) -> bool:
    """A token count: a non-negative int (ERROR and bool are not)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class Calls:
    """The prompts of one question, in the order the flow makes the calls."""

    query_system: str
    query_prompt: str
    answer_system: str | None = None
    answer_prompt: str | None = None
    answer_case_part: str | None = None


@dataclass(frozen=True)
class Speed:
    """This phone's measured rates in tokens/s; None means not measured."""

    prompt_tps: float | None = None
    gen_tps: float | None = None

    @property
    def known(self) -> bool:
        return self.prompt_tps is not None and self.gen_tps is not None


@dataclass(frozen=True)
class Budget:
    """Which rule decided the answer call, and the predicted whole question."""

    rule: str  # "time", "tokens" (speed unknown) or "n_ctx"
    fallback: bool
    predicted_ms: float | None = None


def is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def accept_rate(rate, count, count_min: int) -> bool:
    return (
        is_number(rate)
        and math.isfinite(rate)
        and RATE_MIN <= rate <= RATE_MAX
        and is_number(count)
        and count >= count_min
    )


def update_speed(speed: Speed | None, timings) -> Speed:
    """speed with each rate replaced by timings' rate if that one is usable.

    timings is a llama.rn completion's timings object (prompt_n,
    prompt_per_second, predicted_n, predicted_per_second), or anything else
    (missing), which changes nothing. Priming folds its calls in order, so
    the last priming call's rates win; each answer call then updates it.
    """
    speed = speed or Speed()
    if not isinstance(timings, dict):
        return speed
    prompt, gen = speed.prompt_tps, speed.gen_tps
    rate = timings.get("prompt_per_second")
    if accept_rate(rate, timings.get("prompt_n"), PROMPT_N_MIN):
        prompt = float(rate)
    rate = timings.get("predicted_per_second")
    if accept_rate(rate, timings.get("predicted_n"), PREDICTED_N_MIN):
        gen = float(rate)
    return Speed(prompt, gen)


def speeds_from_priming(reports) -> tuple[Speed | None, Speed | None]:
    """(answer speed, query speed) from priming reports, in priming order.

    reports: (kind, timings) pairs, kind "answer" or "query". Each call kind
    is predicted from its own measurements (ADR 0004, 2026-11-07):
    - The answer speed folds the answer priming reports only (update_speed,
      so the last accepted rate wins). Query priming never sets its prompt
      rate. If answer priming measured no generation rate (it generates one
      token unless it was the measuring call), the query speed's generation
      rate is used: the one MEASURE_TOKENS call is the only generation
      measurement priming makes. Answer calls update the answer speed later.
    - The query speed folds the query priming reports only. The budget never
      reads it (the query call is measured, not predicted).
    The answer speed is None if no report at all was given; the query speed
    is None if no query report was given.
    """
    answer = None
    query = None
    for kind, timings in reports:
        if kind == "answer":
            answer = update_speed(answer, timings)
        else:
            query = update_speed(query, timings)
    if not reports:
        return None, None
    answer = answer or Speed()
    if answer.gen_tps is None and query is not None and query.gen_tps is not None:
        answer = Speed(answer.prompt_tps, query.gen_tps)
    return answer, query


@dataclass(frozen=True)
class Pending:
    """Generated tokens and ms of short answer replies, not yet a rate."""

    n: int = 0
    ms: float = 0.0


def is_short_sample(count, ms) -> bool:
    """A reply too short to give a rate alone: 1 to PREDICTED_N_MIN - 1
    tokens (an integral number), generated in a finite, positive number of ms."""
    return (
        is_integral(count)
        and 1 <= count < PREDICTED_N_MIN
        and is_number(ms)
        and math.isfinite(ms)
        and ms > 0
    )


def update_answer_speed(
    speed: Speed | None, pending: Pending, timings
) -> tuple[Speed, Pending]:
    """update_speed() for an answer call, adding up short replies.

    Answer calls only (never priming or query calls). A reply of fewer than
    PREDICTED_N_MIN generated tokens (for example the 8-token not-found
    sentence) adds its predicted_n and predicted_ms to pending. When pending
    reaches PREDICTED_N_MIN tokens, the generation rate becomes
    pending.n * 1000 / pending.ms (if that rate is accepted) and pending is
    reset. A reply whose own rate is accepted sets the rate as before and
    resets pending. Anything else leaves pending as it is.
    """
    updated = update_speed(speed, timings)
    if not isinstance(timings, dict):
        return updated, pending
    count = timings.get("predicted_n")
    if accept_rate(timings.get("predicted_per_second"), count, PREDICTED_N_MIN):
        return updated, Pending()
    ms = timings.get("predicted_ms")
    if not is_short_sample(count, ms):
        return updated, pending
    total = Pending(pending.n + count, pending.ms + ms)
    if total.n < PREDICTED_N_MIN:
        return updated, total
    rate = total.n * 1000 / total.ms
    if accept_rate(rate, total.n, PREDICTED_N_MIN):
        updated = Speed(updated.prompt_tps, rate)
    return updated, Pending()


def predict_ms(case_tokens: int, elapsed_ms: int, speed: Speed) -> float:
    """The whole question's predicted time if the answer call is made.

    elapsed_ms is measured (session load, query call, search). The order of
    operations is part of the spec, so Python and TypeScript agree exactly.
    """
    return (
        elapsed_ms
        + ANSWER_LOAD_MS
        + case_tokens * 1000 / speed.prompt_tps
        + GEN_TOKENS * 1000 / speed.gen_tps
        + OVERHEAD_MS
    )


def decide_budget(case_tokens: int, elapsed_ms: int, speed: Speed | None) -> Budget:
    if case_tokens > CASE_TOKENS_CTX_MAX:
        return Budget("n_ctx", True)
    if speed is None or not speed.known:
        return Budget("tokens", case_tokens > BUDGET_CASE_TOKENS)
    predicted = predict_ms(case_tokens, elapsed_ms, speed)
    return Budget("time", predicted > BAR_MS, predicted)


@dataclass(frozen=True)
class Outcome:
    path: str
    text: str
    codes: tuple[str, ...] = ()
    # Logged per question for UAT (never the question or the text): the
    # budget decision (None if no answer call was considered) and the number
    # of search results (None if no search result was accepted).
    budget: Budget | None = None
    result_count: int | None = None


ERROR = object()  # a scripted step that throws


def results_list(results: list[dict]) -> str:
    """RESULTS_HEADER, then fallback()'s lines (titles and posted dates)."""
    text = fallback(results)
    if not text.startswith(FALLBACK_HEADER + "\n"):
        raise ValueError("fallback() changed its header line")
    return RESULTS_HEADER + text[len(FALLBACK_HEADER) :]


def safe_results_list(results: list[dict]) -> str | None:
    """results_list(), or None if it can't be built (an unreadable posted_at;
    contract-checked results never have one)."""
    try:
        return results_list(results)
    except ValueError:
        return None


def list_or_last_resort(results: list[dict]) -> str:
    listed = safe_results_list(results)
    return LAST_RESORT_MESSAGE if listed is None else listed


def flow(
    question: str,
    now: datetime,
    prompts: dict[str, str],
    query_reply,
    search_reply=None,
    case_tokens=None,
    answer_reply=None,
    elapsed_ms: int = 0,
    speed: Speed | None = None,
) -> tuple[Outcome, Calls | None, dict | None]:
    """One question through the UAT flow, with every step's result scripted.

    prompts: {"query": the query prompt file's text, "answer": the answer
    prompt file's text}. query_reply, search_reply, case_tokens and
    answer_reply are each the step's value, or ERROR if the step throws.
    elapsed_ms is the time already spent when the budget is decided, and
    speed this phone's measured rates (None: unknown, so the tokens rule).
    Returns the outcome, the prompts sent (None if no call was made) and the
    search arguments (None if no search was made).
    """
    try:
        check_question(question)
    except ContractError:
        return Outcome("question_invalid", LAST_RESORT_MESSAGE), None, None

    query_system = fill_prompt(prompts["query"], now)
    query_prompt = render_qwen3(
        [
            {"role": "system", "content": query_system},
            {"role": "user", "content": question},
        ]
    )
    calls = Calls(query_system, query_prompt)
    if query_reply is ERROR:
        return Outcome("query_error", LAST_RESORT_MESSAGE), calls, None
    try:
        arguments = parse_query_reply(query_reply)
    except ContractError:
        return Outcome("query_invalid", LAST_RESORT_MESSAGE), calls, None

    if search_reply is ERROR:
        return Outcome("search_error", LAST_RESORT_MESSAGE), calls, arguments
    try:
        results = check_results(search_reply)
    except ContractError:
        return Outcome("search_error", LAST_RESORT_MESSAGE), calls, arguments
    count = len(results)
    if not results:
        return Outcome("not_found", NOT_FOUND_MESSAGE, result_count=0), calls, arguments

    answer_system = fill_prompt(prompts["answer"], now)
    user = answer_user_message(question, results)
    answer_prompt = render_qwen3(
        [
            {"role": "system", "content": answer_system},
            {"role": "user", "content": user},
        ]
    )
    calls = Calls(
        query_system,
        query_prompt,
        answer_system,
        answer_prompt,
        case_part(answer_system, user),
    )
    if not is_count(case_tokens):
        outcome = Outcome(
            "answer_error", list_or_last_resort(results), result_count=count
        )
        return outcome, calls, arguments
    budget = decide_budget(case_tokens, elapsed_ms, speed)
    if budget.fallback:
        outcome = Outcome(
            "budget_fallback", list_or_last_resort(results), (), budget, count
        )
        return outcome, calls, arguments
    if answer_reply is ERROR:
        outcome = Outcome(
            "answer_error", list_or_last_resort(results), (), budget, count
        )
        return outcome, calls, arguments
    reply = answer_reply.strip(ASCII_WHITESPACE)
    # The not-found sentence although results exist: show the list instead.
    if reply == NOT_FOUND_MESSAGE:
        outcome = Outcome(
            "answer_not_found", list_or_last_resort(results), (), budget, count
        )
        return outcome, calls, arguments
    try:
        guarded = guard(reply, results, question, [])
    # Defense in depth: results are contract-checked, so the guard should not
    # raise; if it does, never show the unguarded reply.
    except (ValueError, KeyError, TypeError):
        outcome = Outcome(
            "answer_error", list_or_last_resort(results), (), budget, count
        )
        return outcome, calls, arguments
    listed = safe_results_list(results)
    if guarded.fired:
        text = LAST_RESORT_MESSAGE if listed is None else listed
        outcome = Outcome("guard_fired", text, tuple(guarded.codes), budget, count)
    elif listed is None:
        # Unreachable for contract-checked results; never show the reply
        # without its list.
        outcome = Outcome("answer_error", LAST_RESORT_MESSAGE, (), budget, count)
    else:
        text = guarded.text + ANSWER_LIST_SEPARATOR + listed
        outcome = Outcome("answer", text, tuple(guarded.codes), budget, count)
    return outcome, calls, arguments
