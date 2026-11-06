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
   sample errors allow.

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
    BUDGET_CASE_TOKENS,
    MANILA,
    answer_user_message,
    case_part,
    fill_prompt,
    system_turn,
)
from archways_assistant.fakebackend import EXCERPT_CHARS, to_announcement
from archways_assistant.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data" / "local" / "announcements_snapshot.json"
DEFAULT_QUESTION = "What are the latest announcements?"
OPTIONS = {**SAMPLING_OPTIONS, "num_ctx": NUM_CTX, "num_gpu": 0, "num_predict": 1}


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
    args = parser.parse_args()

    snapshot = load_snapshot(args.snapshot)
    rows = search_order(snapshot.rows)
    if len(rows) < 3:
        sys.exit(f"need at least 3 rows, the snapshot has {len(rows)}")
    now = datetime.now(MANILA)
    system = fill_prompt(ANSWER_VERSIONS["v1"][0].read_text(encoding="utf-8"), now)

    def user(results: list[dict]) -> str:
        return answer_user_message(args.question, [to_announcement(r) for r in results])

    with httpx.Client(timeout=600) as client:

        def tokens(text: str) -> int:
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
            return body["prompt_eval_count"]

        def case_tokens(results: list[dict]) -> int:
            return tokens(case_part(system, user(results)))

        version = ollama_version(client)
        print(
            f"ollama {version}  commit {git_commit()}  model {args.model}  "
            f"snapshot {args.snapshot.name}  rows {len(rows)}  question {args.question!r}"
        )
        bodies = [len(row["body"]) for row in rows]
        print(
            f"bodies with tags: {len(snapshot.tagged_ids)} {snapshot.tagged_ids}; "
            f"with character references: {len(snapshot.reference_ids)} "
            f"{snapshot.reference_ids}"
        )
        print(
            f"plain-text body characters: {spread(bodies)}; over {EXCERPT_CHARS} "
            f"(cut): {sum(b > EXCERPT_CHARS for b in bodies)}"
        )

        # 1. System turn + case part = whole prompt.
        whole = system_turn(system) + case_part(system, user(rows[:1]))
        parts = (tokens(system_turn(system)), case_tokens(rows[:1]), tokens(whole))
        print(f"check: system {parts[0]} + case part {parts[1]} = whole {parts[2]}")
        if parts[0] + parts[1] != parts[2]:
            sys.exit("system turn + case part differs from the whole prompt; stopped")

        # 2. Every row as a single result.
        single = {}
        for row in rows:
            single[row["id"]] = case_tokens([row])
        t1 = list(single.values())
        print(f"1 result, exact, every row: {spread(t1)}")
        over_ids = [
            row_id for row_id, count in single.items() if count > BUDGET_CASE_TOKENS
        ]
        print(f"  over {BUDGET_CASE_TOKENS}: {len(over_ids)} of {len(rows)} {over_ids}")
        for row_id, count in sorted(single.items(), key=lambda item: -item[1])[:5]:
            print(f"  largest: id {row_id}: {count}")

        # 3. Exact samples of 2 and 3 results.
        rng = random.Random(args.seed)
        samples = {}
        for k, wanted in ((2, args.pairs), (3, args.triples)):
            combos = list(itertools.combinations(range(len(rows)), k))
            picked = combos if wanted >= len(combos) else rng.sample(combos, wanted)
            samples[k] = [
                (combo, case_tokens([rows[i] for i in combo]))
                for combo in sorted(picked)
            ]
        discounts = [
            sum(single[rows[i]["id"]] for i in combo) - exact
            for combo, exact in samples[2]
        ]
        c = statistics.median(discounts)
        print(
            f"c = median(T1(a) + T1(b) - T2(a, b)) = {c}; discounts {spread(discounts)}"
        )

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
        print(f"estimated case part at the median T1 ({median}): {at_median}")
        all_errors = errors[2] + errors[3]
        low, high = min(all_errors), max(all_errors)
        counts = {}
        for k in (1, 2, 3):
            combos = list(itertools.combinations(range(len(rows)), k))
            if k == 1:
                over = sum(
                    single[rows[i]["id"]] > BUDGET_CASE_TOKENS for (i,) in combos
                )
                counts[k] = {"total": len(combos), "over_exact": over}
                print(
                    f"{k}-result combinations over {BUDGET_CASE_TOKENS}: {over} of {len(combos)} (exact)"
                )
                continue
            values = [estimate(combo) for combo in combos]
            over = sum(v > BUDGET_CASE_TOKENS for v in values)
            surely = sum(v + low > BUDGET_CASE_TOKENS for v in values)
            maybe = sum(v + high > BUDGET_CASE_TOKENS for v in values)
            counts[k] = {
                "total": len(combos),
                "over_estimate": over,
                "over_range": [surely, maybe],
            }
            print(
                f"{k}-result combinations over {BUDGET_CASE_TOKENS}: {over} of {len(combos)} "
                f"by the estimate ({over / len(combos):.1%}); {surely}-{maybe} within the "
                f"sample error {low:+}..{high:+}"
            )

    report = {
        "ollama": version,
        "commit": git_commit(),
        "model": args.model,
        "question": args.question,
        "rows": len(rows),
        "tagged_ids": snapshot.tagged_ids,
        "reference_ids": snapshot.reference_ids,
        "check": dict(zip(("system", "case_part", "whole"), parts, strict=True)),
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
        "combinations": counts,
    }
    out = ROOT / "runs" / f"snapshot_budget_{now:%Y%m%dT%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"report: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
