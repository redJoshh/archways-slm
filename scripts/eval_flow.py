"""Accuracy-phase evaluation: the full UAT flow, cold, scored with scorer_v1.

Usage:
    uv run python scripts/eval_flow.py --out data/local/runs/NAME.json
        [--sets e2e34,taglish10,flow13] [--ids e2e-001,q01] [--model qwen3:0.6b]
    uv run python scripts/eval_flow.py --compare RUN_A.json RUN_B.json

docs/plans/accuracy-phase.md, section 1. Per case:

1. The query call: assistant.flow()'s own query prompt (query v1 filled with
   the case's now, render_qwen3), raw, num_predict 64 (assistant-ts
   N_PREDICT.query), no format (the phone sends no grammar).
2. parse_query_reply, then the on-device-equivalent search:
   feedindex.search_feed (and_v3) over the case's data source: the seed
   file for e2e34 and taglish10, the snapshot for flow13. Arguments the
   contract rejects are a search error, as on the phone.
3. The answer call: flow()'s own answer prompt (answer v1, or v4 with
   --answer-prompt v4), raw,
   num_predict 200 (ANSWER_N_PREDICT), only if the case part fits n_ctx.
   Case tokens are Ollama's prompt_eval_count of flow()'s case part.
4. assistant.flow(..., budget="off") with those replies: the guard, the
   label and the results list, exactly as the phone builds the final text.
   The speed and tokens rules are off; the n_ctx rule stays.
5. evalflow.score_case (scorer_v1) on the final path and text.

Cold settings (ADR 0002): run against one `ollama serve` started with
OLLAMA_NUM_PARALLEL=1; every call sends num_gpu 0, keep_alive 0,
num_ctx 2048 (assistant N_CTX), the greedy SAMPLING_OPTIONS and the
QWEN3_STOP strings.

Prints a header, one line per case (ids, path, flags and reason codes; no
question or reply text) and the totals per set and in total. Writes the
full run (prompts' hashes, replies, final texts, scores) to --out, which
must be inside data/local/ (gitignored: it holds announcement text).

--window window_v1 searches with feedindex.search_feed_window (the phone's
fallback, archways_assistant.phone). --now ISO replaces every case's now: a
READINESS check only (e.g. the defense date). Its scores are not results
(the cases' expected answers assume their own now) and are never compared
with the dev runs; the header records now_override.

--compare prints the case ids whose query reply, answer reply, path or
final text differ between two run files (the baseline determinism check).

Never reads the system clock (every date is the case's now), the held-out
file, .env or a database. Talks only to Ollama on localhost.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import httpx
from check_render import post
from probe_tool_call import (
    OLLAMA_URL,
    SAMPLING_OPTIONS,
    SCHEMA_PATH,
    git_commit,
    ollama_version,
)

from archways_assistant import assistant
from archways_assistant.evalflow import (
    SCORER,
    CaseFileError,
    format_case,
    format_totals,
    load_cases,
    score_case,
    totals,
)
from archways_assistant.fakebackend import AND_V3_RULES, InvalidArguments, is_visible
from archways_assistant.feedindex import (
    search_feed,
    search_feed_retry,
    search_feed_window,
)
from archways_assistant.rank import GATE_THETAS, gate_v1
from archways_assistant.render import QWEN3_STOP
from archways_assistant.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "data" / "local"
SEED_DATA = ROOT / "data" / "seed" / "announcements.json"
SNAPSHOT = LOCAL / "announcements_snapshot.json"
QUERY_PROMPT = ROOT / "prompts" / "e2e_query_v1.txt"
ANSWER_PROMPT = ROOT / "prompts" / "e2e_answer_v1.txt"
# --answer-prompt: v1 is the UAT prompt (the default); v4 is section 3 (f).
ANSWER_PROMPTS = {
    "v1": ANSWER_PROMPT,
    "v4": ROOT / "prompts" / "e2e_answer_v4.txt",
}
SETS = {
    "e2e34": (ROOT / "evals" / "e2e_cases.jsonl", "seed"),
    "taglish10": (ROOT / "evals" / "taglish_cases.jsonl", "seed"),
    "flow13": (LOCAL / "flow_cases.jsonl", "snapshot"),
}
QUERY_N_PREDICT = 64  # assistant-ts N_PREDICT.query
MATCHER = "and_v3"  # feedindex.search_feed
BASE_OPTIONS = {
    **SAMPLING_OPTIONS,
    "num_ctx": assistant.N_CTX,
    "num_gpu": 0,
    "stop": list(QWEN3_STOP),
}
KEEP_ALIVE = 0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_is_dirty() -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(status.stdout.strip())


def load_sources() -> dict[str, list[dict]]:
    return {
        "seed": json.loads(SEED_DATA.read_text(encoding="utf-8")),
        "snapshot": load_snapshot(SNAPSHOT).rows,
    }


def model_digest(client: httpx.Client, model: str) -> str:
    body = client.get(f"{OLLAMA_URL}/api/tags").json()
    for item in body.get("models", []):
        if item.get("name") == model or item.get("model") == model:
            return item.get("digest", "unknown")
    sys.exit(f"model {model} is not pulled in Ollama")


def generate(client: httpx.Client, model: str, prompt: str, n_predict: int) -> dict:
    return post(
        client,
        "/api/generate",
        {
            "model": model,
            "prompt": prompt,
            "raw": True,
            "stream": False,
            "options": {**BASE_OPTIONS, "num_predict": n_predict},
            "keep_alive": KEEP_ALIVE,
        },
    )


def run_case(
    client: httpx.Client,
    model: str,
    case: dict,
    prompts: dict[str, str],
    rows: list[dict],
    contract: dict,
    *,
    rank: str | None = None,
    query_reply: str | None = None,
    retry: str | None = None,
    matcher: str = MATCHER,
    excerpt: str | None = None,
    strip_nf: str | None = None,
    window: str | None = None,
) -> dict:
    """One case through the full flow; returns the replies and the outcome.

    rank: None (newest first, the frozen baseline) or "rank_v1". query_reply:
    a saved query reply to use instead of the query call (--reuse-queries);
    None makes the call. The defaults are the held-out script's path.
    """
    saved_query = query_reply
    question, now = case["question"], case["now"]
    _, calls, _ = assistant.flow(question, now, prompts, assistant.ERROR)
    record = {"query_reply": None, "search": None, "case_tokens": None}
    record["answer_reply"] = None
    query_reply = search_reply = case_tokens = answer_reply = None
    if calls is not None:
        if saved_query is not None:
            query_reply = saved_query
        else:
            query_reply = generate(client, model, calls.query_prompt, QUERY_N_PREDICT)[
                "response"
            ]
        record["query_reply"] = query_reply
        try:
            arguments = assistant.parse_query_reply(query_reply)
        except assistant.ContractError:
            arguments = None
        if arguments is not None:
            try:
                if window is not None:
                    if retry is not None:
                        raise ValueError("window_v1 runs without retry")
                    search_reply, record["fell_back"] = search_feed_window(
                        rows,
                        arguments,
                        now,
                        contract,
                        question=question,
                        rank=rank,
                        matcher=matcher,
                        excerpt=excerpt,
                        window=window,
                    )
                elif retry is None:
                    search_reply = search_feed(
                        rows,
                        arguments,
                        now,
                        contract,
                        question=question,
                        rank=rank,
                        matcher=matcher,
                        excerpt=excerpt,
                    )
                else:
                    if matcher != MATCHER:
                        raise ValueError("retry_v1 runs with and_v3 only")
                    search_reply, record["retried"] = search_feed_retry(
                        rows,
                        arguments,
                        now,
                        contract,
                        question=question,
                        rank=rank,
                        retry=retry,
                    )
                record["search"] = [r["id"] for r in search_reply]
            except InvalidArguments:
                search_reply = assistant.ERROR
                record["search"] = "invalid_arguments"
            _, calls, _ = assistant.flow(
                question, now, prompts, query_reply, search_reply
            )
            if calls.answer_case_part is not None:
                case_tokens = generate(client, model, calls.answer_case_part, 1)[
                    "prompt_eval_count"
                ]
                record["case_tokens"] = case_tokens
                if case_tokens <= assistant.CASE_TOKENS_CTX_MAX:
                    answer_reply = generate(
                        client, model, calls.answer_prompt, assistant.ANSWER_N_PREDICT
                    )["response"]
                    record["answer_reply"] = answer_reply
    outcome, _, arguments = assistant.flow(
        question,
        now,
        prompts,
        query_reply,
        search_reply,
        case_tokens,
        answer_reply,
        budget="off",
        strip_nf=strip_nf,
    )
    results = search_reply if isinstance(search_reply, list) else []
    record.update(
        arguments=arguments,
        results=results,
        path=outcome.path,
        text=outcome.text,
        guard_codes=list(outcome.codes),
        budget_rule=None if outcome.budget is None else outcome.budget.rule,
    )
    return record


def compare(a: Path, b: Path) -> None:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in (a, b)]
    cases = [{c["id"]: c for c in run["cases"]} for run in runs]
    if set(cases[0]) != set(cases[1]):
        sys.exit("the two runs have different case ids")
    keys = ("query_reply", "answer_reply", "path", "text")
    differ = [
        f"{case_id} ({', '.join(k for k in keys if cases[0][case_id][k] != cases[1][case_id][k])})"
        for case_id in cases[0]
        if any(cases[0][case_id][k] != cases[1][case_id][k] for k in keys)
    ]
    print(f"cases {len(cases[0])}  identical {len(cases[0]) - len(differ)}")
    for line in differ:
        print(f"  differs: {line}")


def load_saved_queries(path: Path) -> tuple[dict, dict]:
    """(header, {(set, id): query_reply}) of a saved run file."""
    run = json.loads(path.read_text(encoding="utf-8"))
    return run["header"], {(c["set"], c["id"]): c["query_reply"] for c in run["cases"]}


def places(ids: list[str], sources: list[str]) -> str:
    return (
        " ".join(f"{s}@{ids.index(s) + 1}" if s in ids else f"{s}@-" for s in sources)
        or "trap"
    )


def replay(
    run_path: Path, rank: str, retry: str | None = None, matcher: str = MATCHER
) -> None:
    """Retrieval only, no model call: a saved run's arguments, searched again.

    Before: newest first (and_v3); with matcher and_v4, before is rank with
    and_v3 and after is rank with and_v4.
    """
    run = json.loads(run_path.read_text(encoding="utf-8"))
    sources = load_sources()
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    print(f"replay of {run_path.name} (commit {run['header']['commit']}), rank {rank}")
    for case in run["cases"]:
        if not isinstance(case["arguments"], dict):
            print(f"{case['set']} {case['id']}: no search (path {case['path']})")
            continue
        rows = sources[SETS[case["set"]][1]]
        now = datetime.fromisoformat(case["now"])
        base_rank = rank if matcher != MATCHER else None
        before = [
            r["id"]
            for r in search_feed(
                rows,
                case["arguments"],
                now,
                contract,
                question=case["question"],
                rank=base_rank,
            )
        ]
        if matcher != MATCHER:
            found = search_feed(
                rows,
                case["arguments"],
                now,
                contract,
                question=case["question"],
                rank=rank,
                matcher=matcher,
            )
            retried = False
        else:
            found, retried = search_feed_retry(
                rows,
                case["arguments"],
                now,
                contract,
                question=case["question"],
                rank=rank,
                retry=retry,
            )
        after = [r["id"] for r in found]
        sources_ = list(case["score"]["source_ids"])
        mark = ("" if before == after else "  CHANGED") + (
            "  RETRIED" if retried else ""
        )
        print(
            f"{case['set']} {case['id']}: {before} -> {after}  "
            f"sources {places(before, sources_)} -> {places(after, sources_)}{mark}"
        )


def excerpt_replay(run_path: Path, rank: str, matcher: str, rule: str) -> None:
    """Retrieval only: which results' excerpts the window changes, and which
    dates or numbers it newly shows (facts past character 500)."""
    from archways_assistant.e2escore import claims

    run = json.loads(run_path.read_text(encoding="utf-8"))
    sources = load_sources()
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    print(f"excerpt replay of {run_path.name}: {rule} with {rank} + {matcher}")
    for case in run["cases"]:
        if not isinstance(case["arguments"], dict):
            continue
        rows = sources[SETS[case["set"]][1]]
        now = datetime.fromisoformat(case["now"])
        common = {"question": case["question"], "rank": rank, "matcher": matcher}
        before = search_feed(rows, case["arguments"], now, contract, **common)
        after = search_feed(
            rows, case["arguments"], now, contract, excerpt=rule, **common
        )
        for old, new in zip(before, after, strict=True):
            if old["excerpt"] == new["excerpt"]:
                continue
            was, now_c = claims(old["excerpt"]), claims(new["excerpt"])
            dates = sorted(f"{m:02d}-{d:02d}" for m, d in now_c.dates - was.dates)
            numbers = sorted(now_c.numbers - was.numbers)
            print(
                f"{case['set']} {case['id']}: result {new['id']} window moved; "
                f"newly shown dates {dates} numbers {numbers}"
            )


def nothing_worse(
    base_path: Path, new_path: Path, exclude: set[str], correct_cases: bool = False
) -> bool:
    """accuracy-phase.md section 3, rule 4, per set. Prints every change."""
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in (base_path, new_path)]
    base, new = ({(c["set"], c["id"]): c["score"] for c in r["cases"]} for r in runs)
    if set(base) != set(new):
        sys.exit("the two runs have different cases")
    print(f"nothing-worse check: {base_path.name} -> {new_path.name}")
    if exclude:
        print(f"  reported outside the check: {sorted(exclude)}")
    ok = True
    for name in dict.fromkeys(s for s, _ in base):
        keys = [k for k in base if k[0] == name and k[1] not in exclude]
        helpful = [sum(bool(d[k]["helpful"]) for k in keys) for d in (base, new)]
        wrong = [
            sum(bool(d[k]["wrong"]) and d[k]["answered"] for k in keys)
            for d in (base, new)
        ]
        new_unsafe = [k[1] for k in keys if new[k]["wrong"] and not base[k]["wrong"]]
        lost = [k[1] for k in keys if base[k]["helpful"] and not new[k]["helpful"]]
        gained = [k[1] for k in keys if new[k]["helpful"] and not base[k]["helpful"]]
        correct = [sum(bool(d[k]["correct"]) for k in keys) for d in (base, new)]
        lost_correct = [
            k[1] for k in keys if base[k]["correct"] and not new[k]["correct"]
        ]
        set_ok = helpful[1] >= helpful[0] and not new_unsafe and wrong[1] <= wrong[0]
        if correct_cases:
            set_ok = set_ok and not lost_correct
        ok = ok and set_ok
        print(
            f"{name}: {'OK' if set_ok else 'WORSE'}  helpful {helpful[0]} -> {helpful[1]}  "
            f"ai_correct {correct[0]} -> {correct[1]}  wrong answers {wrong[0]} -> {wrong[1]}  "
            f"new unsafe {new_unsafe}"
        )
        print(f"  helpful lost {lost}  gained {gained}")
        if correct_cases:
            print(f"  AI-correct lost (case by case) {lost_correct}")
        for k in keys:
            b, n = base[k], new[k]
            if b["trap"] and not b["out_of_scope"]:
                print(
                    f"  trap {k[1]}: clean {b['clean']} -> {n['clean']}  "
                    f"path {b['path']} -> {n['path']}  unrelated list "
                    f"{b['unrelated_list']} -> {n['unrelated_list']}"
                )
            elif (b["path"], b["correct"], b["helpful"]) != (
                n["path"],
                n["correct"],
                n["helpful"],
            ):
                print(
                    f"  changed {k[1]}: path {b['path']} -> {n['path']}  correct "
                    f"{b['correct']} -> {n['correct']}  helpful {b['helpful']} -> {n['helpful']}"
                )
    for k in sorted(exclude):
        for s, i in base:
            if i == k:
                b, n = base[(s, i)], new[(s, i)]
                print(
                    f"  outside the check {i}: path {b['path']} -> {n['path']}  wrong {b['wrong']} -> {n['wrong']}"
                )
    print("RESULT: " + ("nothing got worse" if ok else "something got worse"))
    return ok


VERIFY_KEYS = ("arguments", "search", "case_tokens", "answer_reply", "path", "text")


def verify_baseline(base_path: Path, records: list[dict]) -> bool:
    """Every case's path, final text, score and replies equal the frozen run's."""
    base = {
        (c["set"], c["id"]): c
        for c in json.loads(base_path.read_text(encoding="utf-8"))["cases"]
    }
    # Compare as JSON: the in-memory scores hold tuples, the saved run lists.
    new = {(r["set"], r["id"]): json.loads(json.dumps(r)) for r in records}
    if set(base) != set(new):
        print("VERIFY: the case lists differ")
        return False
    differ = []
    for key, b in base.items():
        fields = [k for k in VERIFY_KEYS if b[k] != new[key][k]]
        if b["score"] != new[key]["score"]:
            fields.append("score")
        if fields:
            differ.append(f"{key[1]} ({', '.join(fields)})")
    print(
        f"VERIFY against {base_path.name}: cases {len(base)}  "
        f"identical {len(base) - len(differ)}"
    )
    for line in differ:
        print(f"  differs: {line}")
    return not differ


NOT_ABOUT_HEADER = (
    "I couldn't find an announcement that answers this exactly. These may be related:"
)
# Paths with results where the gate (if it fails) replaces what was shown.
GATED_PATHS = ("answer", "answer_not_found", "guard_fired", "answer_error")


def not_about_text(results: list[dict]) -> str:
    """The not_about final text: the results list under the gate's header."""
    listed = assistant.results_list(results)
    return NOT_ABOUT_HEADER + listed[len(assistant.RESULTS_HEADER) :]


def load_all_cases() -> dict:
    """{(set, id): case} for every dev set (the cases, not the runs)."""
    sources = load_sources()
    known_ids = {name: {row["id"] for row in rows} for name, rows in sources.items()}
    out = {}
    for name, (path, data) in SETS.items():
        for case in load_cases(path, known_ids, default_data=data):
            out[(name, case["id"])] = case
    return out


def gate_record(
    case: dict,
    record: dict,
    rows_by_id: dict,
    offices: set,
    matcher: str,
    p: int,
    q: int,
) -> dict:
    """gate_v1 replayed on one saved record (accuracy-phase.md (d)).

    Exact: the gate only removes the answer call. If the top result (the
    first) fails, the path becomes not_about with the list under the gate's
    header; scorer_v1 scores it as the plain results list (section 0).
    """
    results = record["results"]
    if not results or record["path"] not in GATED_PATHS:
        return record
    top = rows_by_id[results[0]["id"]]
    if gate_v1(
        case["question"],
        top["title"].lower(),
        top["body"].lower(),
        AND_V3_RULES[matcher],
        p,
        q,
    ):
        return record
    listed = assistant.results_list(results)
    score = score_case(case, "not_about", listed, results, rows_by_id, offices)
    return {
        **record,
        "path": "not_about",
        "text": not_about_text(results),
        "answer_reply": None,
        "case_tokens": None,
        "guard_codes": [],
        "gated": True,
        "score": json.loads(json.dumps(asdict(score))),
    }


def gate_run(run: dict, p: int, q: int) -> list[dict]:
    """Every record of a saved run with gate_v1 at theta p/q."""
    sources = load_sources()
    by_id = {name: {row["id"]: row for row in rows} for name, rows in sources.items()}
    offices = {name: {row["office"] for row in rows} for name, rows in sources.items()}
    cases = load_all_cases()
    matcher = run["header"]["matcher"]
    out = []
    for record in run["cases"]:
        case = cases[(record["set"], record["id"])]
        data = case["data"]
        out.append(gate_record(case, record, by_id[data], offices[data], matcher, p, q))
    return out


def gate_fit(run_path: Path) -> None:
    """The pre-registered fit: the largest theta on the grid that, on e2e34
    and taglish10 against theta 0, loses no AI-correct case, keeps the
    helpful count and makes no case unsafe."""
    run = json.loads(run_path.read_text(encoding="utf-8"))
    fit_sets = ("e2e34", "taglish10")
    base = {
        (r["set"], r["id"]): r["score"] for r in run["cases"] if r["set"] in fit_sets
    }
    chosen = (0, 1)
    print(
        f"gate fit on {run_path.name} (matcher {run['header']['matcher']}), sets {fit_sets}"
    )
    for p, q in GATE_THETAS:
        new = {
            (r["set"], r["id"]): r["score"]
            for r in gate_run(run, p, q)
            if r["set"] in fit_sets
        }
        gated = [k[1] for k in base if new[k]["path"] == "not_about"]
        lost = [k[1] for k in base if base[k]["correct"] and not new[k]["correct"]]
        helpful = [sum(bool(d[k]["helpful"]) for k in base) for d in (base, new)]
        unsafe = [k[1] for k in base if new[k]["wrong"] and not base[k]["wrong"]]
        ok = not lost and helpful[1] >= helpful[0] and not unsafe
        if ok:
            chosen = (p, q)
        print(
            f"  theta {p}/{q}: {'OK ' if ok else 'NO '} gated {gated}  correct lost {lost}  "
            f"helpful {helpful[0]} -> {helpful[1]}  new unsafe {unsafe}"
        )
    print(
        f"theta* = {chosen[0]}/{chosen[1]}"
        + ("  (gate does nothing: (d) dropped)" if chosen == (0, 1) else "")
    )


def strip_nf_replay(run_path: Path, strip_nf: str) -> None:
    """No model call: a saved run's replies through flow() with strip_nf.

    Prints the ids whose path or final text would change (no text).
    """
    run = json.loads(run_path.read_text(encoding="utf-8"))
    print(f"strip_nf replay of {run_path.name} (commit {run['header']['commit']})")
    # The prompts shape only the calls, never the outcome of scripted replies.
    prompts = {
        "query": QUERY_PROMPT.read_text(encoding="utf-8"),
        "answer": ANSWER_PROMPT.read_text(encoding="utf-8"),
    }
    changed = 0
    for case in run["cases"]:
        if case["answer_reply"] is None:
            continue
        outcome, _, _ = assistant.flow(
            case["question"],
            datetime.fromisoformat(case["now"]),
            prompts,
            case["query_reply"],
            case["results"],
            case["case_tokens"],
            case["answer_reply"],
            budget="off",
            strip_nf=strip_nf,
        )
        if outcome.path != case["path"] or outcome.text != case["text"]:
            changed += 1
            print(f"{case['set']} {case['id']}: {case['path']} -> {outcome.path}")
    print(f"changed {changed}")


def gate_apply(run_path: Path, p: int, q: int, out: Path) -> None:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    records = gate_run(run, p, q)
    header = {
        **run["header"],
        "gate": "gate_v1",
        "theta": [p, q],
        "gate_replay_of": [run_path.name, sha256(run_path)],
        "replay_commit": git_commit(),
        "replay_tree_dirty": tree_is_dirty(),
    }
    out.write_text(
        json.dumps({"header": header, "cases": records}, ensure_ascii=False, indent=1)
        + "\n",
        encoding="utf-8",
    )
    gated = [r["id"] for r in records if r.get("gated")]
    print(f"gate_v1 theta {p}/{q} on {run_path.name}: gated {gated}")
    print(f"wrote {out.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--sets", default=",".join(SETS))
    parser.add_argument("--ids", default="")
    parser.add_argument("--model", default="qwen3:0.6b")
    parser.add_argument("--compare", nargs=2, type=Path, metavar="RUN")
    parser.add_argument("--rank", choices=["rank_v1"], default=None)
    parser.add_argument("--retry", choices=["retry_v1"], default=None)
    parser.add_argument("--matcher", choices=["and_v3", "and_v4"], default=MATCHER)
    parser.add_argument("--excerpt", choices=["excerpt_v2_centred"], default=None)
    parser.add_argument("--answer-prompt", choices=sorted(ANSWER_PROMPTS), default="v1")
    parser.add_argument("--strip-nf", choices=[assistant.STRIP_NF_V1], default=None)
    parser.add_argument("--window", choices=["window_v1"], default=None)
    parser.add_argument(
        "--now", default=None, help="readiness only: replaces every case's now"
    )
    parser.add_argument("--strip-nf-replay", type=Path, metavar="RUN")
    parser.add_argument("--excerpt-replay", type=Path, metavar="RUN")
    parser.add_argument("--reuse-queries", type=Path, metavar="RUN")
    parser.add_argument("--replay", type=Path, metavar="RUN")
    parser.add_argument(
        "--verify-baseline",
        type=Path,
        metavar="BASE",
        help="baseline configuration with BASE's query replies; must equal BASE",
    )
    parser.add_argument("--nothing-worse", nargs=2, type=Path, metavar=("BASE", "NEW"))
    parser.add_argument("--exclude", default="", help="ids reported outside the check")
    parser.add_argument(
        "--correct-case-by-case",
        action="store_true",
        help="also fail if any case goes from AI-correct to not (d onwards)",
    )
    parser.add_argument("--gate-fit", type=Path, metavar="RUN")
    parser.add_argument("--gate-apply", type=Path, metavar="RUN")
    parser.add_argument("--theta", default=None, help="p/q for --gate-apply")
    args = parser.parse_args()
    if args.nothing_worse:
        exclude = {i for i in args.exclude.split(",") if i}
        ok = nothing_worse(*args.nothing_worse, exclude, args.correct_case_by_case)
        sys.exit(0 if ok else 1)
    if args.compare:
        compare(*args.compare)
        return
    if args.gate_fit:
        gate_fit(args.gate_fit)
        return
    if args.excerpt_replay:
        if args.rank is None or args.excerpt is None:
            parser.error("--excerpt-replay needs --rank and --excerpt")
        excerpt_replay(args.excerpt_replay, args.rank, args.matcher, args.excerpt)
        return
    if args.strip_nf_replay:
        if args.strip_nf is None:
            parser.error("--strip-nf-replay needs --strip-nf")
        strip_nf_replay(args.strip_nf_replay, args.strip_nf)
        return
    if args.gate_apply:
        if args.theta is None or args.out is None:
            parser.error("--gate-apply needs --theta p/q and --out")
        p_text, q_text = args.theta.split("/")
        out = args.out.resolve()
        if not out.is_relative_to(LOCAL.resolve()):
            sys.exit("--out must be inside data/local/ (gitignored)")
        gate_apply(args.gate_apply, int(p_text), int(q_text), out)
        return
    if args.replay:
        if args.rank is None:
            parser.error("--replay needs --rank")
        replay(args.replay, args.rank, args.retry, args.matcher)
        return
    if args.out is None:
        parser.error("--out is required")
    if args.excerpt is not None and (args.rank is None or args.retry is not None):
        parser.error("--excerpt runs with --rank and without --retry")
    if args.retry is not None and args.matcher != MATCHER:
        parser.error("--retry runs with and_v3 only")
    if args.retry is not None and args.rank is None:
        parser.error("--retry needs --rank (retry_v1 orders by rank_v1)")
    if args.window is not None and args.retry is not None:
        parser.error("--window runs without --retry")
    now_override = None
    if args.now is not None:
        now_override = datetime.fromisoformat(args.now)
        if now_override.tzinfo is None:
            parser.error("--now needs an offset")
    if args.verify_baseline is not None:
        if (
            args.window is not None
            or args.now is not None
            or args.rank is not None
            or args.matcher != MATCHER
            or args.excerpt is not None
            or args.answer_prompt != "v1"
            or args.strip_nf is not None
            or args.retry is not None
            or args.reuse_queries is not None
        ):
            parser.error("--verify-baseline runs the baseline configuration only")
        if args.sets != ",".join(SETS) or args.ids:
            parser.error("--verify-baseline runs every case of every dev set")
        args.reuse_queries = args.verify_baseline
    out = args.out.resolve()
    if not out.is_relative_to(LOCAL.resolve()):
        sys.exit("--out must be inside data/local/ (gitignored)")
    names = [name for name in args.sets.split(",") if name]
    unknown = sorted(set(names) - set(SETS))
    if unknown:
        sys.exit(f"unknown sets {unknown}; known: {sorted(SETS)}")
    wanted = {i for i in args.ids.split(",") if i}

    sources = load_sources()
    known_ids = {name: {row["id"] for row in rows} for name, rows in sources.items()}
    by_id = {name: {row["id"]: row for row in rows} for name, rows in sources.items()}
    offices = {name: {row["office"] for row in rows} for name, rows in sources.items()}
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    answer_prompt = ANSWER_PROMPTS[args.answer_prompt]
    prompts = {
        "query": QUERY_PROMPT.read_text(encoding="utf-8"),
        "answer": answer_prompt.read_text(encoding="utf-8"),
    }
    sets = {}
    for name in names:
        path, data = SETS[name]
        if not path.exists():
            sys.exit(f"{name}: case file not found")
        try:
            cases = load_cases(path, known_ids, default_data=data)
        except CaseFileError as error:
            sys.exit(f"{name}: {error}")
        sets[name] = [c for c in cases if not wanted or c["id"] in wanted]
        if now_override is not None:
            sets[name] = [{**c, "now": now_override} for c in sets[name]]

    saved_header, saved = (None, {})
    if args.reuse_queries:
        saved_header, saved = load_saved_queries(args.reuse_queries)
        if saved_header["prompts"]["query"][1] != sha256(QUERY_PROMPT):
            sys.exit("--reuse-queries: that run used another query prompt")
        missing = [
            c["id"] for n, cs in sets.items() for c in cs if (n, c["id"]) not in saved
        ]
        if missing:
            sys.exit(f"--reuse-queries: no saved query reply for {missing}")

    with httpx.Client(timeout=600, trust_env=False) as client:
        header = {
            "ollama": ollama_version(client),
            "model": args.model,
            "model_digest": model_digest(client, args.model),
            "commit": git_commit(),
            "tree_dirty": tree_is_dirty(),
            "scorer": SCORER,
            "matcher": args.matcher,
            "budget": "off",
            "options": BASE_OPTIONS,
            "keep_alive": KEEP_ALIVE,
            "n_predict": {
                "query": QUERY_N_PREDICT,
                "answer": assistant.ANSWER_N_PREDICT,
            },
            "prompts": {
                "query": [QUERY_PROMPT.name, sha256(QUERY_PROMPT)],
                "answer": [answer_prompt.name, sha256(answer_prompt)],
            },
            "case_files": {n: [SETS[n][0].name, sha256(SETS[n][0])] for n in sets},
            "snapshot_sha256": sha256(SNAPSHOT),
            "rank": args.rank,
            "retry": args.retry,
            "excerpt": args.excerpt,
            "answer_prompt": args.answer_prompt,
            "strip_nf": args.strip_nf,
            "window": args.window,
            "now_override": args.now,
            "query_replies_from": None
            if args.reuse_queries is None
            else [args.reuse_queries.name, sha256(args.reuse_queries)],
        }
        if saved_header is not None and (
            saved_header["model_digest"] != header["model_digest"]
            or saved_header["ollama"] != header["ollama"]
        ):
            sys.exit("--reuse-queries: that run used another model or Ollama")
        print(json.dumps(header, ensure_ascii=True))
        for name, cases in sets.items():
            instants = sorted({c["now"].isoformat() for c in cases})
            for instant in instants:
                now = next(c["now"] for c in cases if c["now"].isoformat() == instant)
                rows = sources[SETS[name][1]]
                visible = sum(is_visible(row, now) for row in rows)
                print(f"{name}: now {instant}  visible rows {visible}/{len(rows)}")

        records, all_scores = [], []
        for name, cases in sets.items():
            data_rows = sources[SETS[name][1]]
            scores = []
            for case in cases:
                record = run_case(
                    client,
                    args.model,
                    case,
                    prompts,
                    data_rows,
                    contract,
                    rank=args.rank,
                    query_reply=saved.get((name, case["id"])),
                    retry=args.retry,
                    matcher=args.matcher,
                    excerpt=args.excerpt,
                    strip_nf=args.strip_nf,
                    window=args.window,
                )
                score = score_case(
                    case,
                    record["path"],
                    record["text"],
                    record["results"],
                    by_id[case["data"]],
                    offices[case["data"]],
                )
                scores.append(score)
                print(f"{name} {format_case(score)}", flush=True)
                records.append(
                    {
                        "set": name,
                        "id": case["id"],
                        "question": case["question"],
                        "now": case["now"].isoformat(),
                        **record,
                        "score": asdict(score),
                    }
                )
            all_scores += scores
            print(format_totals(name, totals(scores)))
        print(format_totals("TOTAL", totals(all_scores)))

    out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "header": header,
        "totals": {
            n: totals(
                [s for r, s in zip(records, all_scores, strict=True) if r["set"] == n]
            )
            for n in sets
        },
        "total": totals(all_scores),
        "cases": records,
    }
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(records)} cases to {out.relative_to(ROOT)}")
    if args.verify_baseline is not None:
        base_header = json.loads(args.verify_baseline.read_text(encoding="utf-8"))
        if base_header["header"]["prompts"] != header["prompts"]:
            sys.exit("VERIFY: the prompts differ from the baseline's")
        if not verify_baseline(args.verify_baseline, records):
            sys.exit("VERIFY FAILED: the baseline configuration no longer reproduces")
        print("VERIFY OK: the baseline configuration reproduces the frozen baseline")


if __name__ == "__main__":
    main()
