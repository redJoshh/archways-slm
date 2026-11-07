"""Measure answer-reply lengths (generated tokens) with the UAT prompts.

Evidence, not pytest. Sets GEN_TOKENS for the adaptive time budget
(assistant.py): the nearest-rank 90th percentile of eval_count over every
answer call of the e2e and Taglish dev cases.

UAT configuration: query v1, answer v1, fakebackend's default matcher (and_v2
when GEN_TOKENS was measured on 2026-11-06; and_v3 since 2026-11-07),
qwen3:0.6b. Each call is a raw /api/generate of render_qwen3(), cold
(keep_alive 0), with the probe's sampling options, as in
check_render_qwen3.py (which showed raw = /api/chat for every call). The query
call uses the arguments schema as format, as the probe does. Questions are
only sent to the local model; the output has case ids and numbers only.

eval_count counts generated tokens as Ollama reports them (whether the stop
token is included is not shown; at most 1 token either way).
"""

import argparse
import json
import math
import statistics
from pathlib import Path

import httpx
from check_render import post
from probe_end_to_end import (
    ANSWER_VERSIONS,
    DEFAULT_CASES,
    NUM_CTX,
    QUERY_VERSIONS,
    SEED_DATA,
    load_cases,
    prompt_pair,
)
from probe_tool_call import (
    SAMPLING_OPTIONS,
    SCHEMA_PATH,
    git_commit,
    ollama_version,
)

from archways_assistant.fakebackend import (
    DEFAULT_MATCHER,
    InvalidArguments,
    search_announcements,
)
from archways_assistant.render import render_qwen3

ROOT = Path(__file__).resolve().parents[1]
TAGLISH_CASES = ROOT / "evals" / "taglish_cases.jsonl"
OPTIONS = {**SAMPLING_OPTIONS, "num_ctx": NUM_CTX, "num_gpu": 0}
ANSWER_N_PREDICT = 200  # assistant-ts N_PREDICT.answer
QUERY_N_PREDICT = 64  # assistant-ts N_PREDICT.query


def nearest_rank(values: list[int], percent: int) -> int:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(percent / 100 * len(ordered))) - 1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="qwen3:0.6b")
    args = parser.parse_args()

    answer_path, answer_message, answer_date_in_user = ANSWER_VERSIONS["v1"]
    query_path, query_date_in_user = QUERY_VERSIONS["v1"]
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    rows = json.loads(SEED_DATA.read_text(encoding="utf-8"))
    cases = load_cases(DEFAULT_CASES) + load_cases(TAGLISH_CASES)

    with httpx.Client(timeout=300, trust_env=False) as client:

        def generate(system: str, user: str, n_predict: int, fmt=None) -> dict:
            prompt = render_qwen3(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
            payload = {
                "model": args.model,
                "prompt": prompt,
                "raw": True,
                "stream": False,
                "options": {**OPTIONS, "num_predict": n_predict},
                "keep_alive": 0,
            }
            if fmt is not None:
                payload["format"] = fmt
            return post(client, "/api/generate", payload)

        print(
            f"model={args.model} ollama={ollama_version(client)} commit={git_commit()} "
            f"matcher={DEFAULT_MATCHER} query={query_path.name} answer={answer_path.name} "
            f"cases={len(cases)}"
        )
        counts: dict[str, int] = {}
        capped = []
        for case in cases:
            now, question = case["now"], case["question"]
            query = generate(
                *prompt_pair(query_path, query_date_in_user, now, question),
                QUERY_N_PREDICT,
                contract["$defs"]["arguments"],
            )
            try:
                arguments = json.loads(query["response"])
                results = (
                    search_announcements(rows, arguments, now, contract)
                    if isinstance(arguments, dict)
                    else []
                )
            except (ValueError, InvalidArguments):
                results = []
            if not results:
                print(f"{case['id']}: no answer call")
                continue
            answer = generate(
                *prompt_pair(
                    answer_path,
                    answer_date_in_user,
                    now,
                    answer_message(question, results),
                ),
                ANSWER_N_PREDICT,
            )
            counts[case["id"]] = answer["eval_count"]
            if answer["eval_count"] >= ANSWER_N_PREDICT:
                capped.append(case["id"])
            print(
                f"{case['id']}: {len(results)} result(s), {answer['eval_count']} tokens"
            )

    values = list(counts.values())
    print()
    print(f"answer calls: {len(values)}; hit n_predict {ANSWER_N_PREDICT}: {capped}")
    print(
        f"generated tokens: min {min(values)}, median {statistics.median(values)}, "
        f"p90 (nearest rank) {nearest_rank(values, 90)}, max {max(values)}"
    )
    largest = sorted(counts.items(), key=lambda item: -item[1])[:5]
    print("largest: " + ", ".join(f"{case_id} {n}" for case_id, n in largest))


if __name__ == "__main__":
    main()
