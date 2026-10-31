"""End-to-end probe: question -> search -> final reply, scored on the final reply.

Usage: uv run python scripts/probe_end_to_end.py [--model qwen3:1.7b]
    [--cases evals/e2e_cases.jsonl] [--ids e2e-001,e2e-002] [--repeat 5]
    [--summary-only]
    [--num-gpu 0] [--keep-alive 0] [--matcher and_v1|prefix_v2|and_v2]
    [--answer-prompt v1|v2|v3] [--query-prompt v1|v2|v3]

For each case:
1. Query call. The model writes only the search arguments: Ollama's format
   option is the contract's arguments schema, and the prompt is
   prompts/e2e_query_v1.txt (--query-prompt v2: e2e_query_v2.txt). Every
   case searches.
2. Search. fakebackend runs it over data/seed/announcements.json at the
   case's fixed now, with --matcher (default and_v2). Arguments the contract rejects count as no results,
   as Spring rejects them.
3. Answer call. With no results the reply is the fixed not-found message
   and the model is not called. Otherwise the answer prompt gets the
   question and the results between <announcements> tags. With
   --answer-prompt v1 (the default) that is prompts/e2e_answer_v1.txt and
   the results as JSON; with v2 it is prompts/e2e_answer_v2.txt and the
   compact format of compact_announcements_message(). v2 tells the model
   the list is newest first, so it runs only with --matcher and_v1 or and_v2, whose
   order is newest first. v3 is v1 with today's date moved from the
   system turn to the start of the user message (prompt_pair()), so the
   system turn is the same every day; --query-prompt v2 does the same to
   the query prompt (default v1). --query-prompt v3 is query v1 plus one
   rule: write the keywords in English, even for Filipino or Taglish.
4. Guard. A model reply with a date or number that the retrieved titles
   and excerpts and the question don't support, or with the title
   of a row that must never reach the model, is replaced by a fallback
   built only from the retrieved titles and posted dates.
5. Scoring, on the reply before and after the guard (see e2escore).
   Replies built by code (not-found message, fallback) are not checked
   for unsupported claims. Each failed reply gets failure categories
   (e2escore.categorize); the first is its primary category, which the
   summary counts. A case's optional "exclusion" ("outdated" or
   "injection") says why its must_not_include phrases are wrong. The
   summary also reports unsafe and unhelpful rates (e2escore.UNSAFE and
   UNHELPFUL) before and after the guard. e2escore's wrong-row rule
   applies to every model-written reply: the wrong rows are the retrieved
   rows that are not source rows, plus the case's optional "wrong_rows".

Retrieval hit is scored apart from the reply: a case with source_ids hits
if all of them were retrieved; a case without source_ids hits if nothing
was retrieved.

A case with "out_of_scope": true runs and prints like any other, but is
left out of every summary total (the scorer cannot score a safe decline
yet). The summary lists each such case with whether the guard fired.
Latency and max prompt tokens still include its calls.

Both prompts are frozen before any held-out run (CLAUDE.md). The probe
never reads the system clock: every date comes from the case's now
(tests/test_e2e_harness.py checks this). Every request sends
probe_tool_call.SAMPLING_OPTIONS (greedy: temperature 0, top_k 1, top_p 1,
seed 42) and num_ctx NUM_CTX. A call whose prompt uses
CONTEXT_LIMIT_SHARE of num_ctx or more fails its case, with a warning on
stderr.

--keep-alive sends Ollama's top-level keep_alive field on every chat call
(0 unloads the model after each call); the header then adds keep_alive=...

--repeat N runs the selected cases N times in one process, in order (all
cases, then all again); the header then adds repeat=N and the summary
counts every repeat as a case.

Prints a header line, one block per case (skipped with --summary-only)
and a summary. Talks only to Ollama on localhost. Never reads .env or
touches a database.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import httpx
from probe_tool_call import (
    ROOT,
    SAMPLING_OPTIONS,
    SCHEMA_PATH,
    TODAY_PLACEHOLDER,
    chat,
    display_path,
    git_commit,
    load_prompt,
    model_capabilities,
    ollama_version,
    ratio,
    sampling_header,
    today_text,
)

from archways_assistant.e2escore import (
    CATEGORIES,
    NOT_FOUND_MESSAGE,
    UNHELPFUL,
    UNSAFE,
    categorize,
    failures,
    guard,
    is_fabrication,
    supported,
    unsupported_claims,
    wrong_row_claims,
    wrong_rows_for,
)
from archways_assistant.fakebackend import (
    DEFAULT_MATCHER,
    MATCHERS,
    InvalidArguments,
    is_visible,
    search_announcements,
)

QUERY_PROMPT = ROOT / "prompts" / "e2e_query_v1.txt"
QUERY_PROMPT_V2 = ROOT / "prompts" / "e2e_query_v2.txt"
QUERY_PROMPT_V3 = ROOT / "prompts" / "e2e_query_v3.txt"
ANSWER_PROMPT = ROOT / "prompts" / "e2e_answer_v1.txt"
ANSWER_PROMPT_V2 = ROOT / "prompts" / "e2e_answer_v2.txt"
ANSWER_PROMPT_V3 = ROOT / "prompts" / "e2e_answer_v3.txt"
# The line that query v2 and answer v3 move from the system turn to the
# start of the user turn, word for word as in query v1 and answer v1.
USER_DATE_LINE = "Today is {today} (Asia/Manila)."
DEFAULT_CASES = ROOT / "evals" / "e2e_cases.jsonl"
SEED_DATA = ROOT / "data" / "seed" / "announcements.json"
NUM_CTX = 4096
CONTEXT_LIMIT_SHARE = 0.9
REPLY_PREVIEW_CHARS = 400

CASE_FIELDS = {
    "id": str,
    "question": str,
    "now": str,
    "source_ids": list,
    "must_include": list,
    "must_not_include": list,
    "expects_not_found": bool,
}
# Optional: why a case's must_not_include phrases are wrong (None: not said).
EXCLUSIONS = {None, "outdated", "injection"}
# Other optional case fields: superseded {"current": [...], "old": [...]},
# wrong_claims [...], label (e.g. which batch of cases it was added in),
# out_of_scope (bool, default false: see the module docstring),
# wrong_rows [seed ids] (e2escore.wrong_row_claims), note. The summary splits
# retrieval hit by label.
NO_LABEL = "(no label)"


def load_cases(path: Path) -> list[dict]:
    """Read a JSONL case file: one object per line, blank lines skipped."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        sys.exit(f"Cannot read cases file {path}: {error}")
    seed_ids = {row["id"] for row in json.loads(SEED_DATA.read_text(encoding="utf-8"))}
    cases = []
    seen_ids = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{path}:{line_number}"
        try:
            case = json.loads(line)
        except ValueError as error:
            sys.exit(f"{where}: invalid JSON ({error})")
        if not isinstance(case, dict):
            sys.exit(f"{where}: expected a JSON object")
        for field, kind in CASE_FIELDS.items():
            if not isinstance(case.get(field), kind):
                sys.exit(f"{where}: {field!r} must be a {kind.__name__}")
        try:
            case["now"] = datetime.fromisoformat(case["now"])
        except ValueError as error:
            sys.exit(f"{where}: 'now' is not an ISO date-time ({error})")
        if case["now"].tzinfo is None:
            sys.exit(f"{where}: 'now' needs a UTC offset")
        if case.get("exclusion") not in EXCLUSIONS:
            sys.exit(
                f"{where}: 'exclusion' must be one of {sorted(EXCLUSIONS - {None})}"
            )
        superseded = case.get("superseded")
        if superseded is not None and not (
            isinstance(superseded, dict)
            and set(superseded) == {"current", "old"}
            and all(isinstance(superseded[key], list) for key in superseded)
        ):
            sys.exit(f"{where}: 'superseded' must be {{current: [...], old: [...]}}")
        if not isinstance(case.get("wrong_claims", []), list):
            sys.exit(f"{where}: 'wrong_claims' must be a list")
        if not isinstance(case.get("label", NO_LABEL), str):
            sys.exit(f"{where}: 'label' must be a string")
        if not isinstance(case.get("out_of_scope", False), bool):
            sys.exit(f"{where}: 'out_of_scope' must be a bool")
        wrong_rows = case.get("wrong_rows", [])
        if not (isinstance(wrong_rows, list) and set(wrong_rows) <= seed_ids):
            sys.exit(f"{where}: 'wrong_rows' must be a list of seed ids")
        if case["id"] in seen_ids:
            sys.exit(f"{where}: duplicate id {case['id']!r}")
        seen_ids.add(case["id"])
        cases.append(case)
    if not cases:
        sys.exit(f"Cases file {path} has no cases")
    return cases


def mean_max(values: list[float]) -> str:
    if not values:
        return "n/a"
    return f"{sum(values) / len(values):.2f}s/{max(values):.2f}s"


def context_problem(case_id: str, stage: str, tokens: int | None) -> list[str]:
    """A failure, also printed to stderr, if a prompt nears num_ctx."""
    if tokens is None or tokens < CONTEXT_LIMIT_SHARE * NUM_CTX:
        return []
    problem = f"{stage} prompt used {tokens}/{NUM_CTX} tokens"
    print(f"CONTEXT LIMIT: {case_id} {problem}", file=sys.stderr)
    return [f"context near limit: {problem}"]


def announcements_message(question: str, results: list[dict]) -> str:
    """The answer call's user message: the question, then the results as data."""
    # Escaping "<" keeps the JSON valid and stops row text from closing the tag.
    data = json.dumps(results, ensure_ascii=False, indent=1).replace("<", "\\u003c")
    return f"Question: {question}\n\n<announcements>\n{data}\n</announcements>"


def compact_announcements_message(question: str, results: list[dict]) -> str:
    """The v2 answer call's user message: numbered results, newest first.

    Each result is "N. Title (office, posted YYYY-MM-DD[, year Y])" and the
    excerpt on the next line, with whitespace collapsed; id and priority are
    left out. Raises ValueError if the results are not newest first, since
    the v2 prompt tells the model they are.
    """
    posted = [datetime.fromisoformat(result["posted_at"]) for result in results]
    if any(later > earlier for earlier, later in pairwise(posted)):
        raise ValueError("results are not ordered newest first")
    blocks = []
    for number, (result, when) in enumerate(zip(results, posted), start=1):
        meta = f"{result['office']}, posted {when.date().isoformat()}"
        if result["year_level"] is not None:
            meta += f", year {result['year_level']}"
        # Escaping "<" stops row text from closing the tag, as in v1.
        title = result["title"].replace("<", "\\u003c")
        excerpt = " ".join(result["excerpt"].split()).replace("<", "\\u003c")
        blocks.append(f"{number}. {title} ({meta})\n{excerpt}")
    data = "\n\n".join(blocks)
    return f"Question: {question}\n\n<announcements>\n{data}\n</announcements>"


# --answer-prompt: (prompt file, user message builder, date in the user turn).
ANSWER_VERSIONS = {
    "v1": (ANSWER_PROMPT, announcements_message, False),
    "v2": (ANSWER_PROMPT_V2, compact_announcements_message, False),
    "v3": (ANSWER_PROMPT_V3, announcements_message, True),
}
# --query-prompt: (prompt file, date in the user turn).
QUERY_VERSIONS = {
    "v1": (QUERY_PROMPT, False),
    "v2": (QUERY_PROMPT_V2, True),
    "v3": (QUERY_PROMPT_V3, False),
}


def prompt_pair(
    path: Path, date_in_user: bool, now: datetime, user: str
) -> tuple[str, str]:
    """The system and user messages for one call.

    A prompt with the date in the system turn fills its {today}. One with
    the date in the user turn must not have a {today}; the user message then
    starts with USER_DATE_LINE and a blank line, so the system turn is the
    same on every day.
    """
    if not date_in_user:
        return load_prompt(path, now, None), user
    system = path.read_text(encoding="utf-8").removesuffix("\n")
    if TODAY_PLACEHOLDER in system:
        sys.exit(f"Prompt file {path} has a {TODAY_PLACEHOLDER} placeholder")
    date_line = USER_DATE_LINE.replace(TODAY_PLACEHOLDER, today_text(now))
    return system, f"{date_line}\n\n{user}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--ids", help="comma-separated case IDs to run")
    parser.add_argument(
        "--repeat", type=int, default=1, help="run the selected cases N times"
    )
    parser.add_argument(
        "--summary-only", action="store_true", help="skip per-case blocks"
    )
    parser.add_argument("--matcher", choices=MATCHERS, default=DEFAULT_MATCHER)
    parser.add_argument("--answer-prompt", choices=ANSWER_VERSIONS, default="v1")
    parser.add_argument("--query-prompt", choices=QUERY_VERSIONS, default="v1")
    parser.add_argument(
        "--num-gpu",
        type=int,
        help="Ollama num_gpu option (layers on the GPU; 0 = CPU only). "
        "Not sent unless given.",
    )
    parser.add_argument(
        "--keep-alive",
        help="Ollama keep_alive field (seconds, or a duration such as 5m; "
        "0 = unload after each call). Not sent unless given.",
    )
    args = parser.parse_args()
    show = (lambda *_, **__: None) if args.summary_only else print
    if args.answer_prompt == "v2" and args.matcher not in ("and_v1", "and_v2"):
        sys.exit(
            "--answer-prompt v2 needs --matcher and_v1 or and_v2 (results newest first)"
        )
    answer_prompt, answer_message, answer_date_in_user = ANSWER_VERSIONS[
        args.answer_prompt
    ]
    query_prompt, query_date_in_user = QUERY_VERSIONS[args.query_prompt]

    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    query_format = contract["$defs"]["arguments"]
    rows = json.loads(SEED_DATA.read_text(encoding="utf-8"))
    rows_by_id = {row["id"]: row for row in rows}
    cases = load_cases(args.cases)
    selected_ids = None
    if args.ids is not None:
        selected_ids = [id_.strip() for id_ in args.ids.split(",") if id_.strip()]
        if not selected_ids:
            sys.exit("--ids is empty")
        known = {case["id"] for case in cases}
        unknown = [id_ for id_ in selected_ids if id_ not in known]
        if unknown:
            sys.exit(f"Unknown case id(s): {', '.join(unknown)}")
        cases = [case for case in cases if case["id"] in set(selected_ids)]
    if args.repeat < 1:
        sys.exit("--repeat must be at least 1")
    cases = cases * args.repeat
    # Ollama reads a bare number as seconds and a string as a duration.
    keep_alive = args.keep_alive
    if keep_alive is not None and keep_alive.isdigit():
        keep_alive = int(keep_alive)

    stats = {
        "hits": 0,
        "invalid": 0,
        "answer_calls": 0,
        "guard_fired": 0,
        "failed_before": [],
        "failed_after": [],
        "fabricated_before": [],
        "fabricated_after": [],
        "misses": [],
        "fired": [],
        "near_limit": [],
        # (case id, guard line) for out_of_scope cases, which are not scored.
        "out_of_scope": [],
    }
    kinds = (
        "unsupported",
        "contains",
        "filtered text",
        "stale",
        "misattributed",
        "wrong row",
    )
    kind_counts = {stage: dict.fromkeys(kinds, 0) for stage in ("before", "after")}
    # stage -> group -> case ids with any category in that group.
    groups = {stage: {"unsafe": [], "unhelpful": []} for stage in kind_counts}
    # label -> [hits, cases]
    hits_by_label: dict[str, list[int]] = {}
    category_counts = {stage: dict.fromkeys(CATEGORIES, 0) for stage in kind_counts}
    # stage -> case id -> primary failure category, for the summary's id lists.
    primary = {stage: {} for stage in kind_counts}
    latency = {"query": [], "search": [], "answer": []}
    max_tokens = {"query": 0, "answer": 0}

    with httpx.Client(timeout=300, trust_env=False) as client:
        capabilities = model_capabilities(client, args.model)
        send_think = capabilities is None or "thinking" in capabilities

        def call(system: str, user: str, fmt: dict | None = None):
            payload = {"model": args.model, "stream": False}
            if send_think:
                payload["think"] = False
            payload["options"] = {**SAMPLING_OPTIONS, "num_ctx": NUM_CTX}
            if args.keep_alive is not None:
                payload["keep_alive"] = keep_alive
            if args.num_gpu is not None:
                payload["options"]["num_gpu"] = args.num_gpu
            if fmt is not None:
                payload["format"] = fmt
            payload["messages"] = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            started = time.perf_counter()
            body = chat(client, payload)
            elapsed = time.perf_counter() - started
            content = (body.get("message") or {}).get("content") or ""
            return content, body.get("prompt_eval_count"), elapsed

        shown_capabilities = (
            "unknown" if capabilities is None else ",".join(capabilities) or "none"
        )
        nows = sorted({case["now"].isoformat() for case in cases})
        ids_field = f"ids={','.join(selected_ids)} " if selected_ids else ""
        # Only on repeated runs, so a normal run's header is unchanged.
        repeat_field = f"repeat={args.repeat} " if args.repeat > 1 else ""
        keep_alive_field = (
            f"keep_alive={args.keep_alive} " if args.keep_alive is not None else ""
        )
        print(
            f"model={args.model} capabilities={shown_capabilities} "
            f"query_prompt={display_path(query_prompt)} "
            f"answer_prompt={display_path(answer_prompt)} "
            f"cases={display_path(args.cases)} seed_data={display_path(SEED_DATA)} "
            f"matcher={args.matcher} "
            f"{ids_field}{repeat_field}now={','.join(nows)} "
            f"{sampling_header()} num_ctx={NUM_CTX} "
            f"num_gpu={'default' if args.num_gpu is None else args.num_gpu} "
            f"{keep_alive_field}"
            f"ollama={ollama_version(client)} commit={git_commit()}"
        )
        print()

        for number, case in enumerate(cases, start=1):
            now, question = case["now"], case["question"]
            forbidden = [row["title"] for row in rows if not is_visible(row, now)]
            context_problems = []
            scored = not case.get("out_of_scope", False)

            show(f"[{number}/{len(cases)}] {case['id']}: {question}")
            if not scored:
                show("  out of scope: reported, not scored")

            # 1. Query call: the model writes only the arguments.
            content, tokens, elapsed = call(
                *prompt_pair(query_prompt, query_date_in_user, now, question),
                query_format,
            )
            latency["query"].append(elapsed)
            if tokens is not None:
                max_tokens["query"] = max(max_tokens["query"], tokens)
            context_problems += context_problem(case["id"], "query", tokens)
            show(
                f"  query: {content.strip()} | prompt tokens {tokens}/{NUM_CTX} "
                f"| {elapsed:.2f}s"
            )

            # 2. Search with the fake backend.
            results, invalid = [], None
            try:
                arguments = json.loads(content)
            except ValueError:
                arguments = None
            started = time.perf_counter()
            if not isinstance(arguments, dict):
                invalid = "reply is not a JSON object"
            else:
                try:
                    results = search_announcements(
                        rows, arguments, now, contract, matcher=args.matcher
                    )
                except InvalidArguments as error:
                    invalid = str(error)
            latency["search"].append(time.perf_counter() - started)
            ids = [result["id"] for result in results]
            if case["source_ids"]:
                hit = set(case["source_ids"]) <= set(ids)
            else:
                hit = not ids
            if scored:
                stats["hits"] += hit
                label = case.get("label", NO_LABEL)
                label_hits = hits_by_label.setdefault(label, [0, 0])
                label_hits[0] += hit
                label_hits[1] += 1
                if not hit:
                    stats["misses"].append(case["id"])
            if invalid:
                stats["invalid"] += scored
                show(f"  search: invalid arguments ({invalid})", end="")
            else:
                show(f"  search: {len(ids)} result(s) {ids}", end="")
            show(f" | retrieval hit: {'yes' if hit else 'no'}")

            # 3. Answer call, or the fixed not-found message without one.
            if results:
                stats["answer_calls"] += scored
                raw, tokens, elapsed = call(
                    *prompt_pair(
                        answer_prompt,
                        answer_date_in_user,
                        now,
                        answer_message(question, results),
                    )
                )
                raw = raw.strip()
                latency["answer"].append(elapsed)
                if tokens is not None:
                    max_tokens["answer"] = max(max_tokens["answer"], tokens)
                context_problems += context_problem(case["id"], "answer", tokens)
                show(f"  answer: prompt tokens {tokens}/{NUM_CTX} | {elapsed:.2f}s")
                raw_unsupported = unsupported_claims(raw, supported(results, question))
                # 4. Guard.
                guarded = guard(raw, results, question, forbidden)
                final = guarded.text
                fired = guarded.fired
                final_unsupported = [] if guarded.fired else raw_unsupported
                if guarded.fired and scored:
                    stats["guard_fired"] += 1
                    stats["fired"].append(case["id"])
                guard_line = (
                    f"fired ({'; '.join(guarded.reasons)})"
                    if guarded.fired
                    else "not fired"
                )
            else:
                show("  answer: not called (no results)")
                raw = final = NOT_FOUND_MESSAGE
                raw_unsupported = final_unsupported = []
                fired = False
                guard_line = "not run"
            show(f"  reply: {raw.replace(chr(10), ' | ')[:REPLY_PREVIEW_CHARS]}")
            show(f"  guard: {guard_line}")
            if final != raw:
                show(f"  final: {final.replace(chr(10), ' | ')[:REPLY_PREVIEW_CHARS]}")
            if not scored:
                stats["out_of_scope"].append((case["id"], guard_line))
                show()
                continue

            # 5. Score before and after the guard.
            expected = {
                "must_include": case["must_include"],
                "must_not_include": case["must_not_include"],
                "expects_not_found": case["expects_not_found"],
                "forbidden": forbidden,
                "superseded": case.get("superseded"),
                "wrong_claims": case.get("wrong_claims", []),
            }
            retrieved_text = "\n".join(f"{r['title']}\n{r['excerpt']}" for r in results)
            wrong_ids = wrong_rows_for(
                named=case.get("wrong_rows", []),
                retrieved=ids,
                sources=case["source_ids"],
            )
            wrong_rows = [rows_by_id[id_] for id_ in wrong_ids]
            source_rows = [rows_by_id[id_] for id_ in case["source_ids"]]
            for stage, reply, unsupported, code_built, fallback_used in (
                ("before", raw, raw_unsupported, not results, False),
                ("after", final, final_unsupported, not results or fired, fired),
            ):
                wrong_row = (
                    []
                    if code_built
                    else wrong_row_claims(reply, wrong_rows, source_rows, question)
                )
                problems = failures(
                    reply, **expected, unsupported=unsupported, wrong_row=wrong_row
                )
                problems += context_problems
                categories = categorize(
                    reply,
                    problems,
                    retrieval_hit=hit,
                    expects_not_found=case["expects_not_found"],
                    must_not_include=case["must_not_include"],
                    exclusion=case.get("exclusion"),
                    retrieved_text=retrieved_text,
                    code_built=code_built,
                    fallback_used=fallback_used,
                )
                if problems:
                    stats[f"failed_{stage}"].append(case["id"])
                    category_counts[stage][categories[0]] += 1
                    primary[stage][case["id"]] = categories[0]
                if UNSAFE & set(categories):
                    groups[stage]["unsafe"].append(case["id"])
                if UNHELPFUL & set(categories):
                    groups[stage]["unhelpful"].append(case["id"])
                fabricated = [p for p in problems if is_fabrication(p)]
                if fabricated:
                    stats[f"fabricated_{stage}"].append(case["id"])
                for kind in kinds:
                    kind_counts[stage][kind] += any(
                        p.startswith(f"{kind} ") for p in fabricated
                    )
                verdict = (
                    f"FAIL [{', '.join(categories)}] ({'; '.join(problems)})"
                    if problems
                    else "PASS"
                )
                show(f"  {stage} guard: {verdict}")
            if context_problems:
                stats["near_limit"].append(case["id"])
            show()

    total = len(cases) - len(stats["out_of_scope"])
    answered = stats["answer_calls"]

    def ids_line(label: str, ids: list[str]) -> None:
        print(f"  {label}: {', '.join(ids) if ids else 'none'}")

    def kinds_text(stage: str) -> str:
        return ", ".join(f"{kind} {kind_counts[stage][kind]}" for kind in kinds)

    def categories_text(stage: str) -> str:
        counts = category_counts[stage]
        return ", ".join(f"{category} {counts[category]}" for category in CATEGORIES)

    def with_category(stage: str) -> list[str]:
        return [f"{id_} ({primary[stage][id_]})" for id_ in stats[f"failed_{stage}"]]

    print("Summary")
    print(f"  cases: {total}")
    print(f"  retrieval hit: {ratio(stats['hits'], total)}")
    print(f"  invalid search arguments: {stats['invalid']}/{total}")
    print(
        f"  answer calls: {answered} "
        f"(not-found without a model call: {total - answered})"
    )
    print(f"  guard fired: {ratio(stats['guard_fired'], answered)} answer calls")
    print(f"  failed before guards: {ratio(len(stats['failed_before']), total)}")
    print(f"  failed after guards: {ratio(len(stats['failed_after']), total)}")
    print(
        f"  fabrication before guards: {len(stats['fabricated_before'])}/{total} "
        f"cases ({kinds_text('before')})"
    )
    print(
        f"  fabrication after guards: {len(stats['fabricated_after'])}/{total} "
        f"cases ({kinds_text('after')})"
    )
    print(f"  primary failure category before guards: {categories_text('before')}")
    print(f"  primary failure category after guards: {categories_text('after')}")
    for stage in ("before", "after"):
        print(
            f"  unsafe {stage} guards: {ratio(len(groups[stage]['unsafe']), total)}; "
            f"unhelpful {stage} guards: "
            f"{ratio(len(groups[stage]['unhelpful']), total)}"
        )
    for label, (label_hit, label_total) in hits_by_label.items():
        print(f"  retrieval hit, {label}: {ratio(label_hit, label_total)}")
    print(
        f"  max prompt tokens: query {max_tokens['query']}/{NUM_CTX}, "
        f"answer {max_tokens['answer']}/{NUM_CTX}; "
        f"near-limit cases: {len(stats['near_limit'])}"
    )
    print(
        f"  latency mean/max: query {mean_max(latency['query'])}, "
        f"search {mean_max(latency['search'])}, "
        f"answer {mean_max(latency['answer'])}"
    )
    ids_line("retrieval misses", stats["misses"])
    ids_line("guard fired", stats["fired"])
    ids_line("failed before guards", with_category("before"))
    ids_line("failed after guards", with_category("after"))
    ids_line("fabrication after guards", stats["fabricated_after"])
    ids_line("unsafe after guards", groups["after"]["unsafe"])
    ids_line("unhelpful after guards", groups["after"]["unhelpful"])
    ids_line(
        "out of scope, not scored",
        [f"{id_} (guard {line})" for id_, line in stats["out_of_scope"]],
    )


if __name__ == "__main__":
    main()
