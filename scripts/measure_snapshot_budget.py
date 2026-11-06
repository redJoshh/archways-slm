"""Measure answer-call case parts on a local announcements snapshot.

Evidence, not pytest. Measurement only: no prompt or contract change.

The case part is assistant.case_part() of the answer v1 call: the user turn
plus the empty think block, the part the UAT budget rule compares with
BUDGET_CASE_TOKENS (200). Each row (body already plain text by the
contract v2 excerpt rule, see archways_assistant.excerpt) becomes a result
with fakebackend.to_announcement() (excerpt = body cut to 500 characters,
posted_at with +08:00), and the user message is
assistant.answer_user_message(question, results).

Tokens are Qwen tokens from Ollama: prompt_eval_count of a raw
/api/generate with keep_alive 0 (cold, so no prompt cache), num_predict 1.

1. Check once that system turn + case part = whole prompt in tokens, so
   counting the case part alone is the budget's count.
2. Exact case-part tokens for EVERY row as a single result (T1).
3. Exact case-part tokens for a random sample of 2- and 3-result
   combinations, in search order (newest published_at first, then id).
   Fit c = median(T1(a) + T1(b) - T2(a, b)) and estimate any k-result
   case part as sum(T1) - (k - 1) * c. Report the estimate's error on the
   samples (exact - estimate).
4. Estimates at the median T1 for 1, 2 and 3 results, and how many of all
   C(n, k) combinations are over 200: by the estimate, and the range the
   sample errors allow. Also how many would be over the 15 s time rule at
   the Redmi 10C's rates (REDMI), by the estimate.

--excerpt-chars repeats steps 2-4 for each excerpt length (default 500,
the contract's): each plain-text body is cut to that many code points, the
contract v2 order (plain text first, then the cut). The same samples are
used for every length, and identical case parts are counted once.

The question is fixed (--question). It was written for this script, not
taken from any eval file.

Prints ids and numbers only, never announcement text. Writes the same
numbers as JSON to runs/ (gitignored). Talks only to Ollama on localhost;
reads the snapshot file, never a database.
"""

import argparse
import itertools
import json
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path

import httpx
from check_render import post
from probe_end_to_end import ANSWER_VERSIONS, NUM_CTX
from probe_tool_call import SAMPLING_OPTIONS, git_commit, ollama_version

from archways_assistant.assistant import (
    BAR_MS,
    BUDGET_CASE_TOKENS,
    MANILA,
    Speed,
    answer_user_message,
    case_part,
    fill_prompt,
    predict_ms,
    system_turn,
)
from archways_assistant.fakebackend import EXCERPT_CHARS, to_announcement
from archways_assistant.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data" / "local" / "announcements_snapshot.json"
DEFAULT_QUESTION = "What are the latest announcements?"
OPTIONS = {**SAMPLING_OPTIONS, "num_ctx": NUM_CTX, "num_gpu": 0, "num_predict": 1}
# The time rule at the Redmi 10C's rates (2026-10-31: 28 prompt and 10.4
# generated tokens/s) with 2.2 s already spent (session loads and the query
# call measured 2.2 s for e2e-009; the Spring search is not included).
REDMI = Speed(28.0, 10.4)
REDMI_ELAPSED_MS = 2200


def search_order(rows: list[dict]) -> list[dict]:
    by_id = sorted(rows, key=lambda row: row["id"])
    return sorted(by_id, key=lambda row: row["published_at"], reverse=True)


def spread(values: list[int]) -> dict:
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--model", default="qwen3:0.6b")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--pairs", type=int, default=50, help="exact 2-result samples")
    parser.add_argument(
        "--triples", type=int, default=50, help="exact 3-result samples"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--excerpt-chars",
        default=str(EXCERPT_CHARS),
        help="comma-separated excerpt lengths in code points",
    )
    args = parser.parse_args()
    lengths = [int(part) for part in args.excerpt_chars.split(",") if part.strip()]
    if not lengths or min(lengths) < 1 or max(lengths) > EXCERPT_CHARS:
        sys.exit(f"excerpt lengths must be 1-{EXCERPT_CHARS}")

    snapshot = load_snapshot(args.snapshot)
    rows = search_order(snapshot.rows)
    if len(rows) < 3:
        sys.exit(f"need at least 3 rows, the snapshot has {len(rows)}")
    now = datetime.now(MANILA)
    system = fill_prompt(ANSWER_VERSIONS["v1"][0].read_text(encoding="utf-8"), now)
    rng = random.Random(args.seed)
    picked = {}
    for k, wanted in ((2, args.pairs), (3, args.triples)):
        combos = list(itertools.combinations(range(len(rows)), k))
        chosen = combos if wanted >= len(combos) else rng.sample(combos, wanted)
        picked[k] = sorted(chosen)

    def user(results: list[dict], chars: int) -> str:
        announcements = []
        for row in results:
            announcement = to_announcement(row)
            announcement["excerpt"] = row["body"][:chars]
            announcements.append(announcement)
        return answer_user_message(args.question, announcements)

    with httpx.Client(timeout=600) as client:
        cache: dict[str, int] = {}

        def tokens(text: str) -> int:
            if text not in cache:
                body = post(
                    client,
                    "/api/generate",
                    {
                        "model": args.model,
                        "prompt": text,
                        "raw": True,
                        "stream": False,
                        "options": OPTIONS,
                        "keep_alive": 0,
                    },
                )
                cache[text] = body["prompt_eval_count"]
            return cache[text]

        def case_tokens(results: list[dict], chars: int) -> int:
            return tokens(case_part(system, user(results, chars)))

        version = ollama_version(client)
        print(
            f"ollama {version}  commit {git_commit()}  model {args.model}  "
            f"snapshot {args.snapshot.name}  rows {len(rows)}  "
            f"question {args.question!r}  excerpt lengths {lengths}"
        )
        bodies = [len(row["body"]) for row in rows]
        print(
            f"bodies with tags: {len(snapshot.tagged_ids)} {snapshot.tagged_ids}; "
            f"with character references: {len(snapshot.reference_ids)} "
            f"{snapshot.reference_ids}"
        )
        print(f"plain-text body characters: {spread(bodies)}")

        # 1. System turn + case part = whole prompt.
        whole = system_turn(system) + case_part(system, user(rows[:1], lengths[0]))
        parts = (
            tokens(system_turn(system)),
            case_tokens(rows[:1], lengths[0]),
            tokens(whole),
        )
        print(f"check: system {parts[0]} + case part {parts[1]} = whole {parts[2]}")
        if parts[0] + parts[1] != parts[2]:
            sys.exit("system turn + case part differs from the whole prompt; stopped")

        results = {}
        for chars in lengths:
            results[str(chars)] = measure_length(rows, chars, case_tokens, picked)

    report = {
        "ollama": version,
        "commit": git_commit(),
        "model": args.model,
        "question": args.question,
        "rows": len(rows),
        "tagged_ids": snapshot.tagged_ids,
        "reference_ids": snapshot.reference_ids,
        "check": dict(zip(("system", "case_part", "whole"), parts, strict=True)),
        "redmi": {
            "speed": [REDMI.prompt_tps, REDMI.gen_tps],
            "elapsed_ms": REDMI_ELAPSED_MS,
        },
        "lengths": results,
    }
    out = ROOT / "runs" / f"snapshot_budget_{now:%Y%m%dT%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"report: {out.relative_to(ROOT)}")


def measure_length(rows: list[dict], chars: int, case_tokens, picked) -> dict:
    """Steps 2-4 at one excerpt length; prints and returns the numbers."""
    print()
    cut = [row["id"] for row in rows if len(row["body"]) > chars]
    print(f"== excerpt {chars} characters: bodies cut {len(cut)} of {len(rows)}")

    # 2. Every row as a single result.
    single = {row["id"]: case_tokens([row], chars) for row in rows}
    t1 = list(single.values())
    print(f"1 result, exact, every row: {spread(t1)}")
    over_ids = [i for i, count in single.items() if count > BUDGET_CASE_TOKENS]
    print(f"  over {BUDGET_CASE_TOKENS}: {len(over_ids)} of {len(rows)} {over_ids}")
    for row_id, count in sorted(single.items(), key=lambda item: -item[1])[:5]:
        print(f"  largest: id {row_id}: {count}")

    # 3. Exact samples of 2 and 3 results.
    samples = {
        k: [
            (combo, case_tokens([rows[i] for i in combo], chars)) for combo in picked[k]
        ]
        for k in (2, 3)
    }
    discounts = [
        sum(single[rows[i]["id"]] for i in combo) - exact for combo, exact in samples[2]
    ]
    c = statistics.median(discounts)
    print(f"c = median(T1(a) + T1(b) - T2(a, b)) = {c}; discounts {spread(discounts)}")

    def estimate(combo: tuple[int, ...]) -> float:
        return sum(single[rows[i]["id"]] for i in combo) - (len(combo) - 1) * c

    errors = {
        k: [exact - estimate(combo) for combo, exact in samples[k]] for k in (2, 3)
    }
    for k in (2, 3):
        exact_over = sum(exact > BUDGET_CASE_TOKENS for _, exact in samples[k])
        print(
            f"{k} results, exact, {len(samples[k])} samples: "
            f"{spread([e for _, e in samples[k]])}; over {BUDGET_CASE_TOKENS}: "
            f"{exact_over}; estimate error (exact - estimate) {spread(errors[k])}"
        )

    # 4. Estimates at the median, and all combinations.
    median = statistics.median(t1)
    at_median = {k: k * median - (k - 1) * c for k in (1, 2, 3)}
    redmi_at_median = {
        k: round(predict_ms(v, REDMI_ELAPSED_MS, REDMI)) for k, v in at_median.items()
    }
    print(f"estimated case part at the median T1 ({median}): {at_median}")
    print(f"  predicted whole question at the Redmi rates, ms: {redmi_at_median}")
    all_errors = errors[2] + errors[3]
    low, high = min(all_errors), max(all_errors)
    counts = {}
    for k in (1, 2, 3):
        combos = list(itertools.combinations(range(len(rows)), k))
        values = [estimate(combo) for combo in combos]
        over = sum(v > BUDGET_CASE_TOKENS for v in values)
        slow = sum(predict_ms(v, REDMI_ELAPSED_MS, REDMI) > BAR_MS for v in values)
        counts[k] = {"total": len(combos), "over_200": over, "over_15s_redmi": slow}
        exactness = "exact" if k == 1 else f"estimate, sample error {low:+}..{high:+}"
        print(
            f"{k}-result combinations: over {BUDGET_CASE_TOKENS} tokens {over} of "
            f"{len(combos)}; over {BAR_MS // 1000} s at the Redmi rates {slow} of "
            f"{len(combos)} ({exactness})"
        )
    return {
        "bodies_cut": cut,
        "single": single,
        "c": c,
        "samples": {
            str(k): [
                {"ids": [rows[i]["id"] for i in combo], "exact": exact}
                for combo, exact in samples[k]
            ]
            for k in (2, 3)
        },
        "estimate_at_median": at_median,
        "redmi_ms_at_median": redmi_at_median,
        "combinations": counts,
    }


if __name__ == "__main__":
    main()
