"""Precompute the phone flow test's search results (cold Ollama queries).

Evidence, not pytest. For each test question in --questions (a local,
gitignored JSON list of {id, category, question, expected}):

1. The query call exactly as the phone sends it (assistant.py flow():
   query v1 filled with today's Manila date, render_qwen3, raw), cold
   (keep_alive 0), the probe's sampling options, num_predict 64 (assistant-ts
   N_PREDICT.query), CPU only, NO format: assistant-ts sends no grammar, so
   this is the reply the phone should reproduce. A second call WITH the
   arguments schema as format (what the probes ran) is recorded too, only
   to show whether the two differ.
2. parse_query_reply() (the phone's parser) on the no-format reply, then
   fakebackend.search_announcements(..., matcher and_v3, the default since
   2026-11-07) on the snapshot at
   the same instant. An invalid reply gets results null (the phone never
   searches then).

Writes one JSON file for the test app's fake search (--out, which must be
in a gitignored folder: it holds announcement text). Prints ids and
numbers only. Talks only to Ollama on localhost; reads the snapshot file,
never a database.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
from check_render import post
from probe_end_to_end import NUM_CTX, QUERY_PROMPT
from probe_tool_call import SAMPLING_OPTIONS, SCHEMA_PATH, git_commit, ollama_version

from archways_assistant.assistant import (
    MANILA,
    ContractError,
    fill_prompt,
    parse_query_reply,
)
from archways_assistant.fakebackend import search_announcements
from archways_assistant.render import render_qwen3
from archways_assistant.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data" / "local" / "announcements_snapshot.json"
DEFAULT_QUESTIONS = ROOT / "data" / "local" / "flow_test_questions.json"
QUERY_N_PREDICT = 64  # assistant-ts N_PREDICT.query
MATCHER = "and_v3"
OPTIONS = {
    **SAMPLING_OPTIONS,
    "num_ctx": NUM_CTX,
    "num_gpu": 0,
    "num_predict": QUERY_N_PREDICT,
}
QUESTION_KEYS = {"id", "category", "question", "expected"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="qwen3:0.6b")
    args = parser.parse_args()

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    for item in questions:
        if set(item) != QUESTION_KEYS:
            sys.exit(
                f"question {item.get('id')!r}: keys must be {sorted(QUESTION_KEYS)}"
            )
    rows = load_snapshot(args.snapshot).rows
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    now = datetime.now(MANILA)
    system = fill_prompt(QUERY_PROMPT.read_text(encoding="utf-8"), now)

    with httpx.Client(timeout=300, trust_env=False) as client:

        def query(question: str, fmt=None) -> str:
            payload = {
                "model": args.model,
                "prompt": render_qwen3(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": question},
                    ]
                ),
                "raw": True,
                "stream": False,
                "options": OPTIONS,
                "keep_alive": 0,
            }
            if fmt is not None:
                payload["format"] = fmt
            return post(client, "/api/generate", payload)["response"]

        version = ollama_version(client)
        print(
            f"ollama {version}  commit {git_commit()}  model {args.model}  "
            f"matcher {MATCHER}  snapshot rows {len(rows)}  questions {len(questions)}"
        )
        cases = []
        for item in questions:
            reply = query(item["question"])
            reply_format = query(item["question"], contract["$defs"]["arguments"])
            try:
                arguments = parse_query_reply(reply)
            except ContractError:
                arguments = None
            results = (
                None
                if arguments is None
                else search_announcements(rows, arguments, now, contract, MATCHER)
            )
            cases.append(
                {
                    **item,
                    "ollama_reply": reply,
                    "ollama_arguments": arguments,
                    "ollama_reply_with_format": reply_format,
                    "results": results,
                }
            )
            ids = None if results is None else [r["id"] for r in results]
            print(
                f"{item['id']}: valid {arguments is not None}, "
                f"same with format {reply.strip() == reply_format.strip()}, "
                f"results {ids}"
            )

    bundle = {
        "generated_at": now.isoformat(),
        "now_ms": int(now.timestamp() * 1000),
        "ollama": version,
        "commit": git_commit(),
        "model": args.model,
        "matcher": MATCHER,
        "rows": len(rows),
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(cases)} cases to {args.out}")


if __name__ == "__main__":
    main()
