"""Probe whether a local Ollama model calls search_announcements correctly.

Usage: uv run python scripts/probe_tool_call.py [--model qwen3:1.7b]
    [--tool-mode native|prompt] [--prompt prompts/system_v1.txt]
    [--questions evals/dev_questions.jsonl] [--ids dev-001,dev-004]

--tool-mode native (default) sends the tool in Ollama's tools field.
--tool-mode prompt is for models without tool support: the tool definition
goes into the system prompt and the reply text is parsed with toolparse.
Its default prompt is prompts/system_v1_prompt_mode.txt.

Prints a header line (model, tool mode, model capabilities, prompt,
questions, Ollama version, git commit, date) so runs can be compared, then
one block per question and a summary with per-category results.

--ids runs only the listed question IDs, in file order; the header then adds
ids=... and the summary covers only those questions. An unknown ID exits.

Each block starts with the question ID, e.g. "[3/30] dev-004: <question>".
This is a deliberate one-time format change (2026-10-15, the commit that
added --ids); older raw outputs start with "[3/30] <question>".

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

from archways_assistant.toolparse import Malformed, ToolCall, parse_reply

ROOT = Path(__file__).resolve().parent.parent
TOOL_PATH = ROOT / "generated" / "search_announcements.tool.json"
SCHEMA_PATH = ROOT / "contracts" / "search_announcements.schema.json"
OLLAMA_URL = "http://localhost:11434"
TOOL_NAME = "search_announcements"
DEFAULT_PROMPTS = {
    "native": ROOT / "prompts" / "system_v1.txt",
    "prompt": ROOT / "prompts" / "system_v1_prompt_mode.txt",
}
DEFAULT_QUESTIONS = ROOT / "evals" / "dev_questions.jsonl"
TODAY_PLACEHOLDER = "{today}"
TOOL_PLACEHOLDER = "{tool_definition}"

# Manila has no daylight saving time, so a fixed offset is exact.
MANILA = timezone(timedelta(hours=8), "Asia/Manila")

MAX_QUERY_WORDS = 6
CONTENT_PREVIEW_CHARS = 200

QUESTION_FIELDS = {"id": str, "question": str, "expects_tool": bool, "category": str}


def load_prompt(path: Path, now: datetime, tool_definition: str | None) -> str:
    """Read a prompt file and fill its {today} placeholder with the Manila date.

    In prompt mode (tool_definition given) the file must have a
    {tool_definition} placeholder, which is filled with it. In native mode it
    must not, so a prompt can't silently run in the wrong mode.
    """
    try:
        template = path.read_text(encoding="utf-8").removesuffix("\n")
    except OSError as error:
        sys.exit(f"Cannot read prompt file {path}: {error}")
    if TODAY_PLACEHOLDER not in template:
        sys.exit(f"Prompt file {path} has no {TODAY_PLACEHOLDER} placeholder")
    has_tool_placeholder = TOOL_PLACEHOLDER in template
    if tool_definition is not None and not has_tool_placeholder:
        sys.exit(f"Prompt file {path} has no {TOOL_PLACEHOLDER} placeholder")
    if tool_definition is None and has_tool_placeholder:
        sys.exit(f"Prompt file {path} is for --tool-mode prompt")
    # str.replace, not str.format, so prompts may contain other braces.
    prompt = template.replace(TODAY_PLACEHOLDER, f"{now:%A}, {now:%Y-%m-%d}")
    if tool_definition is not None:
        prompt = prompt.replace(TOOL_PLACEHOLDER, tool_definition)
    return prompt


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


def model_capabilities(client: httpx.Client, model: str) -> list[str] | None:
    """The model's capabilities from /api/show, or None if Ollama doesn't list them."""
    try:
        response = client.post(f"{OLLAMA_URL}/api/show", json={"model": model})
    except httpx.ConnectError:
        sys.exit("Ollama not reachable at localhost:11434")
    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text}
    if response.status_code != 200 or "error" in body:
        sys.exit(
            f"Cannot read model {model!r} (HTTP {response.status_code}): "
            f"{body.get('error', body)}"
        )
    capabilities = body.get("capabilities")
    return capabilities if isinstance(capabilities, list) else None


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
    parser.add_argument("--tool-mode", choices=["native", "prompt"], default="native")
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--ids", help="comma-separated question IDs to run")
    args = parser.parse_args()
    prompt_mode = args.tool_mode == "prompt"
    prompt_path = args.prompt or DEFAULT_PROMPTS[args.tool_mode]

    tool_text = TOOL_PATH.read_text(encoding="utf-8")
    tool = json.loads(tool_text)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema["$defs"]["arguments"], format_checker=FormatChecker()
    )
    now = datetime.now(MANILA)
    tool_definition = tool_text.removesuffix("\n") if prompt_mode else None
    system = load_prompt(prompt_path, now, tool_definition)
    questions = load_questions(args.questions)
    selected_ids = None
    if args.ids is not None:
        selected_ids = [id_.strip() for id_ in args.ids.split(",") if id_.strip()]
        if not selected_ids:
            sys.exit("--ids is empty")
        known = {item["id"] for item in questions}
        unknown = [id_ for id_ in selected_ids if id_ not in known]
        if unknown:
            sys.exit(
                f"Unknown question id(s) in {display_path(args.questions)}: "
                f"{', '.join(unknown)}"
            )
        wanted = set(selected_ids)
        questions = [item for item in questions if item["id"] in wanted]

    correct_decisions = 0
    tool_calls_total = 0
    valid_calls = 0
    sentence_like_total = 0
    malformed_total = 0
    # category -> {"correct": int, "total": int, "wrong": [ids]}, in file order.
    categories: dict[str, dict] = {}

    with httpx.Client(timeout=300, trust_env=False) as client:
        capabilities = model_capabilities(client, args.model)
        # Models without thinking (e.g. gemma3) reject the think option. If
        # Ollama doesn't report capabilities, keep sending it as before.
        send_think = capabilities is None or "thinking" in capabilities
        shown_capabilities = (
            "unknown" if capabilities is None else ",".join(capabilities) or "none"
        )
        # Only on subset runs, so a full run's header is unchanged.
        ids_field = f"ids={','.join(selected_ids)} " if selected_ids else ""
        print(
            f"model={args.model} tool_mode={args.tool_mode} "
            f"capabilities={shown_capabilities} prompt={display_path(prompt_path)} "
            f"questions={display_path(args.questions)} {ids_field}"
            f"ollama={ollama_version(client)} commit={git_commit()} "
            f"today={now:%Y-%m-%d}"
        )
        print()
        for number, item in enumerate(questions, start=1):
            question, expects_tool = item["question"], item["expects_tool"]
            payload = {"model": args.model, "stream": False}
            if send_think:
                payload["think"] = False
            payload["options"] = {"temperature": 0}
            if not prompt_mode:
                payload["tools"] = [tool]
            payload["messages"] = [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ]
            started = time.perf_counter()
            body = chat(client, payload)
            latency = time.perf_counter() - started

            message = body.get("message", {})
            # (name, arguments) pairs, so both modes share the checks below.
            calls = []
            malformed = None
            if prompt_mode:
                parsed = parse_reply(message.get("content") or "", TOOL_NAME)
                if isinstance(parsed, ToolCall):
                    calls.append((parsed.name, parsed.arguments))
                elif isinstance(parsed, Malformed):
                    malformed = parsed.reason
                    malformed_total += 1
            else:
                for call in message.get("tool_calls") or []:
                    function = call.get("function", {})
                    calls.append((function.get("name"), function.get("arguments")))
            called = bool(calls)
            # A malformed attempt is a wrong decision whatever was expected.
            decision_ok = malformed is None and called == expects_tool
            correct_decisions += decision_ok
            stats = categories.setdefault(
                item["category"], {"correct": 0, "total": 0, "wrong": []}
            )
            stats["total"] += 1
            if decision_ok:
                stats["correct"] += 1
            else:
                stats["wrong"].append(item["id"])

            print(f"[{number}/{len(questions)}] {item['id']}: {question}")
            shown_called = "malformed" if malformed else "yes" if called else "no"
            print(
                f"  tool called: {shown_called} | "
                f"expected: {'yes' if expects_tool else 'no'} | "
                f"{'OK' if decision_ok else 'WRONG'}"
            )
            if malformed:
                print(f"  parse error: {malformed}")
            for name, arguments in calls:
                tool_calls_total += 1
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
    if prompt_mode:
        print(f"  malformed: {malformed_total}/{len(questions)}")
    print("Per category (correct tool decisions)")
    for category, stats in categories.items():
        wrong = f" (wrong: {', '.join(stats['wrong'])})" if stats["wrong"] else ""
        print(f"  {category}: {stats['correct']}/{stats['total']}{wrong}")


if __name__ == "__main__":
    main()
