"""Evidence that render_qwen3() gives Ollama the same prompt as /api/chat.

Usage: uv run python scripts/check_render_qwen3.py [--model qwen3:0.6b]
    [--answer-prompt v1|v2|v3] [--query-prompt v1|v2|v3]
    [--cases evals/e2e_cases.jsonl] [--ids e2e-001,e2e-002]

Run it against one `ollama serve` started with OLLAMA_NUM_PARALLEL=1 (ADR
0002). It is an evidence script, not part of pytest.

1. Checks that Ollama's template for the model equals
   render.QWEN3_OLLAMA_TEMPLATE, and that its stop parameters equal
   render.QWEN3_STOP; stops if not.
2. Start-of-text probe: /api/generate with "raw": true and the prompt
   "<|im_start|>" (one special token), then "<|im_start|><|im_start|>",
   and prints both prompt_eval_counts. 1 and 2 mean Ollama added no
   start-of-text token in raw mode.
3. For each case, every call of the pipeline is made twice:
   (a) /api/chat with the system and user messages and "think": false, and
   (b) /api/generate with "raw": true and render_qwen3() of the same
       messages.
   The query call sends the contract's arguments schema as "format" in both.
   Its search runs exactly as in scripts/probe_end_to_end.py (default
   matcher). If the search returns rows, the answer call is compared the
   same way, without "format".
   Every call uses SAMPLING_OPTIONS, num_ctx NUM_CTX, num_gpu 0 and
   keep_alive 0, so it starts cold and prompt_eval_count counts the whole
   prompt. prompt_eval_count and the reply must match exactly. At the first
   difference it prints both values and stops with exit code 1.

Talks only to Ollama on localhost. Never reads .env or touches a database.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx
from check_render import first_difference, post
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
    sampling_header,
)

from archways_assistant.fakebackend import (
    DEFAULT_MATCHER,
    InvalidArguments,
    search_announcements,
)
from archways_assistant.render import QWEN3_OLLAMA_TEMPLATE, QWEN3_STOP, render_qwen3

OPTIONS = {**SAMPLING_OPTIONS, "num_ctx": NUM_CTX, "num_gpu": 0}
KEEP_ALIVE = 0


def stop_parameters(parameters: str) -> tuple[str, ...]:
    """The stop strings in /api/show's "parameters" text, in order."""
    stops = []
    for line in parameters.splitlines():
        name, _, value = line.strip().partition(" ")
        if name == "stop":
            stops.append(json.loads(value.strip()))
    return tuple(stops)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="qwen3:0.6b")
    parser.add_argument("--answer-prompt", choices=ANSWER_VERSIONS, default="v1")
    parser.add_argument("--query-prompt", choices=QUERY_VERSIONS, default="v1")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--ids", help="comma-separated case IDs to run")
    args = parser.parse_args()

    answer_path, answer_message, answer_date_in_user = ANSWER_VERSIONS[
        args.answer_prompt
    ]
    query_path, query_date_in_user = QUERY_VERSIONS[args.query_prompt]
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    query_format = contract["$defs"]["arguments"]
    rows = json.loads(SEED_DATA.read_text(encoding="utf-8"))
    cases = load_cases(args.cases)
    if args.ids:
        wanted = {id_.strip() for id_ in args.ids.split(",") if id_.strip()}
        unknown = wanted - {case["id"] for case in cases}
        if unknown:
            sys.exit(f"Unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in wanted]

    with httpx.Client(timeout=300, trust_env=False) as client:
        print(
            f"model={args.model} {sampling_header()} num_ctx={NUM_CTX} num_gpu=0 "
            f"keep_alive={KEEP_ALIVE} answer_prompt={answer_path.name} "
            f"query_prompt={query_path.name} matcher={DEFAULT_MATCHER} "
            f"ollama={ollama_version(client)} commit={git_commit()}"
        )
        shown = post(client, "/api/show", {"model": args.model})
        template = shown.get("template")
        if template != QWEN3_OLLAMA_TEMPLATE:
            print("template: DIFFERS from render.QWEN3_OLLAMA_TEMPLATE")
            print(first_difference(template or "", QWEN3_OLLAMA_TEMPLATE))
            sys.exit(1)
        print("template: identical to render.QWEN3_OLLAMA_TEMPLATE")
        stops = stop_parameters(shown.get("parameters") or "")
        if sorted(stops) != sorted(QWEN3_STOP):
            print(f"stop parameters: {stops!r}, expected {QWEN3_STOP!r}")
            sys.exit(1)
        print(f"stop parameters: {stops!r} (same set as render.QWEN3_STOP)")

        def generate(prompt: str, fmt: dict | None = None, **options) -> dict:
            payload = {
                "model": args.model,
                "prompt": prompt,
                "raw": True,
                "stream": False,
                "options": {**OPTIONS, **options},
                "keep_alive": KEEP_ALIVE,
            }
            if fmt is not None:
                payload["format"] = fmt
            return post(client, "/api/generate", payload)

        def chat(system: str, user: str, fmt: dict | None = None) -> dict:
            payload = {
                "model": args.model,
                "stream": False,
                "think": False,
                "options": dict(OPTIONS),
                "keep_alive": KEEP_ALIVE,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if fmt is not None:
                payload["format"] = fmt
            return post(client, "/api/chat", payload)

        for prompt in ("<|im_start|>", "<|im_start|><|im_start|>"):
            body = generate(prompt, num_predict=1)
            print(
                f"start-of-text probe: raw prompt {prompt!r} -> "
                f"prompt_eval_count {body.get('prompt_eval_count')}"
            )
        print()

        compared = {"query": 0, "answer": 0}

        def compare(label: str, kind: str, system: str, user: str, fmt=None) -> str:
            via_chat = chat(system, user, fmt)
            rendered = render_qwen3(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
            via_raw = generate(rendered, fmt)
            counts = (
                via_chat.get("prompt_eval_count"),
                via_raw.get("prompt_eval_count"),
            )
            replies = (via_chat["message"]["content"], via_raw["response"])
            print(
                f"{label} {kind}: prompt_eval_count chat {counts[0]} / raw "
                f"{counts[1]}; reply "
                f"{'identical' if replies[0] == replies[1] else 'DIFFERS'}"
            )
            if counts[0] != counts[1] or counts[0] is None:
                print(f"  stopped: prompt_eval_count differs ({counts})")
                sys.exit(1)
            if replies[0] != replies[1]:
                print("  stopped: reply differs; " + first_difference(*replies))
                sys.exit(1)
            compared[kind] += 1
            return replies[0]

        not_called = 0
        for number, case in enumerate(cases, start=1):
            now, question = case["now"], case["question"]
            label = f"[{number}/{len(cases)}] {case['id']}"
            query_reply = compare(
                label,
                "query",
                *prompt_pair(query_path, query_date_in_user, now, question),
                query_format,
            )
            results = []
            try:
                arguments = json.loads(query_reply)
                if isinstance(arguments, dict):
                    results = search_announcements(rows, arguments, now, contract)
            except (ValueError, InvalidArguments):
                results = []
            if not results:
                not_called += 1
                print(f"{label} answer: not called (no results)")
                continue
            compare(
                label,
                "answer",
                *prompt_pair(
                    answer_path,
                    answer_date_in_user,
                    now,
                    answer_message(question, results),
                ),
            )

    print()
    print("Summary")
    print(f"  query calls: {compared['query']}/{len(cases)} identical")
    print(
        f"  answer calls: {compared['answer']} identical (no answer call: {not_called})"
    )


if __name__ == "__main__":
    main()
