"""Probe whether a local Ollama model calls search_announcements correctly.

Usage: uv run python scripts/probe_tool_call.py [--model qwen3:1.7b]
    [--prompt prompts/system_v1.txt] [--questions evals/dev_questions.jsonl]

Prints a header line (model, prompt, questions, Ollama version, git commit,
date) so runs can be compared, then one block per question and a summary
with per-category results.

Talks only to Ollama on localhost. Never reads .env or touches a database.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
TOOL_PATH = ROOT / "generated" / "search_announcements.tool.json"
SCHEMA_PATH = ROOT / "contracts" / "search_announcements.schema.json"
OLLAMA_URL = "http://localhost:11434"
TOOL_NAME = "search_announcements"
DEFAULT_PROMPT = ROOT / "prompts" / "system_v1.txt"
DEFAULT_QUESTIONS = ROOT / "evals" / "dev_questions.jsonl"
TODAY_PLACEHOLDER = "{today}"

# Manila has no daylight saving time, so a fixed offset is exact.
MANILA = timezone(timedelta(hours=8), "Asia/Manila")

MAX_QUERY_WORDS = 6
CONTENT_PREVIEW_CHARS = 200

QUESTION_FIELDS = {"id": str, "question": str, "expects_tool": bool, "category": str}


def load_prompt(path: Path, now: datetime) -> str:
    """Read a prompt file and fill its {today} placeholder with the Manila date."""
    try:
        template = path.read_text(encoding="utf-8").removesuffix("\n")
    except OSError as error:
        sys.exit(f"Cannot read prompt file {path}: {error}")
    if TODAY_PLACEHOLDER not in template:
        sys.exit(f"Prompt file {path} has no {TODAY_PLACEHOLDER} placeholder")
    # str.replace, not str.format, so prompts may contain other braces.
    return template.replace(TODAY_PLACEHOLDER, f"{now:%A}, {now:%Y-%m-%d}")


def load_questions(path: Path) -> list[dict]:
    """Read a JSONL question file: one object per line, blank lines skipped.

    Each object needs id, question, expects_tool and category. Extra keys
    (e.g. notes in a hand-written file) are ignored.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        sys.exit(f"Cannot read questions file {path}: {error}")
    questions = []
    seen_ids = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{path}:{line_number}"
        try:
            item = json.loads(line)
        except ValueError as error:
            sys.exit(f"{where}: invalid JSON ({error})")
        if not isinstance(item, dict):
            sys.exit(f"{where}: expected a JSON object")
        for field, kind in QUESTION_FIELDS.items():
            if not isinstance(item.get(field), kind):
                sys.exit(f"{where}: {field!r} must be a {kind.__name__}")
        if item["id"] in seen_ids:
            sys.exit(f"{where}: duplicate id {item['id']!r}")
        seen_ids.add(item["id"])
        questions.append(item)
    if not questions:
        sys.exit(f"Questions file {path} has no questions")
    return questions


def display_path(path: Path) -> str:
    """Show paths inside the repo relative to it, so headers compare across machines."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def git_commit() -> str:
    """Short HEAD hash plus "-dirty" if the work tree has any changes."""

    def git(*command: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(ROOT), *command],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip()

    commit = git("rev-parse", "--short", "HEAD")
    if commit is None:
        return "unknown"
    return f"{commit}-dirty" if git("status", "--porcelain") else commit


def ollama_version(client: httpx.Client) -> str:
    try:
        response = client.get(f"{OLLAMA_URL}/api/version")
    except httpx.ConnectError:
        sys.exit("Ollama not reachable at localhost:11434")
    try:
        return response.json().get("version", "unknown")
    except ValueError:
        return "unknown"


def tokens_per_second(body: dict) -> str:
    count, duration = body.get("eval_count"), body.get("eval_duration")
    if not count or not duration:
        return "n/a"
    return f"{count / duration * 1e9:.1f}"


def seconds(nanoseconds) -> str:
    return "n/a" if nanoseconds is None else f"{nanoseconds / 1e9:.2f}s"


def is_sentence_like(query: str) -> bool:
    return len(query.split()) > MAX_QUERY_WORDS or query.rstrip().endswith("?")


def chat(client: httpx.Client, payload: dict) -> dict:
    try:
        response = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
    except httpx.ConnectError:
        sys.exit("Ollama not reachable at localhost:11434")
    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text}
    if response.status_code != 200 or "error" in body:
        sys.exit(
            f"Ollama rejected the request (HTTP {response.status_code}): "
            f"{body.get('error', body)}"
        )
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    args = parser.parse_args()

    tool = json.loads(TOOL_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema["$defs"]["arguments"], format_checker=FormatChecker()
    )
    now = datetime.now(MANILA)
    system = load_prompt(args.prompt, now)
    questions = load_questions(args.questions)

    correct_decisions = 0
    tool_calls_total = 0
    valid_calls = 0
    sentence_like_total = 0
    # category -> {"correct": int, "total": int, "wrong": [ids]}, in file order.
    categories: dict[str, dict] = {}

    with httpx.Client(timeout=300, trust_env=False) as client:
        print(
            f"model={args.model} prompt={display_path(args.prompt)} "
            f"questions={display_path(args.questions)} "
            f"ollama={ollama_version(client)} commit={git_commit()} "
            f"today={now:%Y-%m-%d}"
        )
        print()
        for number, item in enumerate(questions, start=1):
            question, expects_tool = item["question"], item["expects_tool"]
            payload = {
                "model": args.model,
                "stream": False,
                "think": False,
                "options": {"temperature": 0},
                "tools": [tool],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
            }
            started = time.perf_counter()
            body = chat(client, payload)
            latency = time.perf_counter() - started

            message = body.get("message", {})
            calls = message.get("tool_calls") or []
            called = bool(calls)
            decision_ok = called == expects_tool
            correct_decisions += decision_ok
            stats = categories.setdefault(
                item["category"], {"correct": 0, "total": 0, "wrong": []}
            )
            stats["total"] += 1
            if decision_ok:
                stats["correct"] += 1
            else:
                stats["wrong"].append(item["id"])

            print(f"[{number}/{len(questions)}] {question}")
            print(
                f"  tool called: {'yes' if called else 'no'} | "
                f"expected: {'yes' if expects_tool else 'no'} | "
                f"{'OK' if decision_ok else 'WRONG'}"
            )
            for call in calls:
                tool_calls_total += 1
                function = call.get("function", {})
                name = function.get("name")
                arguments = function.get("arguments")
                print(f"  call: {name} {json.dumps(arguments, ensure_ascii=False)}")

                errors = []
                if name != TOOL_NAME:
                    errors.append(f"unexpected tool name {name!r}")
                errors += [
                    f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
                    for e in validator.iter_errors(arguments)
                ]
                if errors:
                    print(f"  arguments valid: no ({'; '.join(errors)})")
                else:
                    valid_calls += 1
                    print("  arguments valid: yes")

                query = arguments.get("query") if isinstance(arguments, dict) else None
                if isinstance(query, str):
                    flag = ""
                    if is_sentence_like(query):
                        sentence_like_total += 1
                        flag = " (sentence-like)"
                    print(f"  query words: {len(query.split())}{flag}")

            print(
                f"  latency: {latency:.2f}s "
                f"(ollama total {seconds(body.get('total_duration'))}, "
                f"load {seconds(body.get('load_duration'))})"
            )
            print(
                f"  prompt tokens: {body.get('prompt_eval_count', 'n/a')} | "
                f"tokens/s: {tokens_per_second(body)}"
            )
            content = (message.get("content") or "").strip().replace("\n", " ")
            if content:
                print(f"  reply: {content[:CONTENT_PREVIEW_CHARS]}")
            print()

    print("Summary")
    print(f"  correct tool decisions: {correct_decisions}/{len(questions)}")
    print(f"  valid arguments: {valid_calls}/{tool_calls_total} tool calls")
    print(f"  sentence-like queries: {sentence_like_total}/{tool_calls_total}")
    print("Per category (correct tool decisions)")
    for category, stats in categories.items():
        wrong = f" (wrong: {', '.join(stats['wrong'])})" if stats["wrong"] else ""
        print(f"  {category}: {stats['correct']}/{stats['total']}{wrong}")


if __name__ == "__main__":
    main()
