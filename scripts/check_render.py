"""Evidence that render_gemma3() gives Ollama the same prompt as /api/chat.

Usage: uv run python scripts/check_render.py [--model gemma3:1b]
    [--cases evals/e2e_cases.jsonl] [--ids e2e-001,e2e-002]

Run it against one `ollama serve` started with OLLAMA_NUM_PARALLEL=1 (ADR
0002). It is an evidence script, not part of pytest.

1. Checks that Ollama's template for the model equals
   render.OLLAMA_TEMPLATE; stops if not.
2. Start-of-text probe: /api/generate with "raw": true and the prompt
   "<start_of_turn>" (one special token), then "<bos><start_of_turn>",
   and prints both prompt_eval_counts. A count of 1 for the first means
   Ollama added no start-of-text token in raw mode; 2 means it added one.
   This reading assumes both strings tokenize as special tokens.
3. For each case: the query call and search, exactly as in
   scripts/probe_end_to_end.py (default matcher). If the search returns
   rows, the answer call runs twice:
   (a) /api/chat with the system and user messages, and
   (b) /api/generate with "raw": true and render_gemma3() of the same
       messages.
   Both calls use SAMPLING_OPTIONS, num_ctx NUM_CTX, num_gpu 0 and
   keep_alive 0, so every call starts cold and prompt_eval_count counts the
   whole prompt. prompt_eval_count and the reply must match exactly. At the
   first difference it prints both values and stops with exit code 1.

Talks only to Ollama on localhost. Never reads .env or touches a database.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx
from probe_end_to_end import (
    ANSWER_PROMPT,
    DEFAULT_CASES,
    NUM_CTX,
    QUERY_PROMPT,
    SEED_DATA,
    announcements_message,
    load_cases,
)
from probe_tool_call import (
    OLLAMA_URL,
    SAMPLING_OPTIONS,
    SCHEMA_PATH,
    chat,
    git_commit,
    load_prompt,
    ollama_version,
    sampling_header,
)

from archways_assistant.fakebackend import InvalidArguments, search_announcements
from archways_assistant.render import OLLAMA_TEMPLATE, render_gemma3

OPTIONS = {**SAMPLING_OPTIONS, "num_ctx": NUM_CTX, "num_gpu": 0}
KEEP_ALIVE = 0
SNIPPET_CHARS = 60


def post(client: httpx.Client, path: str, payload: dict) -> dict:
    try:
        response = client.post(f"{OLLAMA_URL}{path}", json=payload)
    except httpx.ConnectError:
        sys.exit("Ollama not reachable at localhost:11434")
    body = response.json()
    if response.status_code != 200 or "error" in body:
        sys.exit(f"Ollama rejected {path} (HTTP {response.status_code}): {body}")
    return body


def raw_generate(client: httpx.Client, model: str, prompt: str, **options) -> dict:
    return post(
        client,
        "/api/generate",
        {
            "model": model,
            "prompt": prompt,
            "raw": True,
            "stream": False,
            "options": {**OPTIONS, **options},
            "keep_alive": KEEP_ALIVE,
        },
    )


def first_difference(a: str, b: str) -> str:
    index = next(
        (i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y),
        min(len(a), len(b)),
    )
    start = max(0, index - SNIPPET_CHARS // 2)
    return (
        f"first difference at character {index} "
        f"(lengths {len(a)} and {len(b)}):\n"
        f"  chat: {a[start : index + SNIPPET_CHARS]!r}\n"
        f"  raw:  {b[start : index + SNIPPET_CHARS]!r}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="gemma3:1b")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--ids", help="comma-separated case IDs to run")
    args = parser.parse_args()

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
            f"keep_alive={KEEP_ALIVE} ollama={ollama_version(client)} "
            f"commit={git_commit()}"
        )
        template = post(client, "/api/show", {"model": args.model}).get("template")
        if template != OLLAMA_TEMPLATE:
            print("template: DIFFERS from render.OLLAMA_TEMPLATE")
            print(first_difference(template or "", OLLAMA_TEMPLATE))
            sys.exit(1)
        print("template: identical to render.OLLAMA_TEMPLATE")

        for prompt in ("<start_of_turn>", "<bos><start_of_turn>"):
            body = raw_generate(client, args.model, prompt, num_predict=1)
            print(
                f"start-of-text probe: raw prompt {prompt!r} -> "
                f"prompt_eval_count {body.get('prompt_eval_count')}"
            )
        print()

        def chat_call(system: str, user: str, fmt: dict | None = None) -> dict:
            payload = {
                "model": args.model,
                "stream": False,
                "options": dict(OPTIONS),
                "keep_alive": KEEP_ALIVE,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if fmt is not None:
                payload["format"] = fmt
            return chat(client, payload)

        compared = same_counts = same_replies = not_called = 0
        for number, case in enumerate(cases, start=1):
            now, question = case["now"], case["question"]
            label = f"[{number}/{len(cases)}] {case['id']}"
            query = chat_call(
                load_prompt(QUERY_PROMPT, now, None), question, query_format
            )
            results = []
            try:
                arguments = json.loads(query["message"]["content"])
                if isinstance(arguments, dict):
                    results = search_announcements(rows, arguments, now, contract)
            except (ValueError, InvalidArguments):
                results = []
            if not results:
                not_called += 1
                print(f"{label}: no answer call (no results)")
                continue

            system = load_prompt(ANSWER_PROMPT, now, None)
            user = announcements_message(question, results)
            via_chat = chat_call(system, user)
            rendered = render_gemma3(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
            via_raw = raw_generate(client, args.model, rendered)
            compared += 1
            counts = (
                via_chat.get("prompt_eval_count"),
                via_raw.get("prompt_eval_count"),
            )
            replies = (via_chat["message"]["content"], via_raw["response"])
            print(
                f"{label}: prompt_eval_count chat {counts[0]} / raw {counts[1]}; "
                f"reply {'identical' if replies[0] == replies[1] else 'DIFFERS'}"
            )
            if counts[0] != counts[1]:
                print(
                    f"  stopped: prompt_eval_count differs ({counts[0]} vs {counts[1]})"
                )
                sys.exit(1)
            same_counts += 1
            if replies[0] != replies[1]:
                print("  stopped: reply differs; " + first_difference(*replies))
                sys.exit(1)
            same_replies += 1

    print()
    print("Summary")
    print(f"  answer calls compared: {compared} (no answer call: {not_called})")
    print(f"  identical prompt_eval_count: {same_counts}/{compared}")
    print(f"  identical replies: {same_replies}/{compared}")


if __name__ == "__main__":
    main()
