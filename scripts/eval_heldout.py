"""Held-out run: the accuracy-phase harness, printing totals only.

Usage (the user runs this; Claude Code never does):
    uv run python scripts/eval_heldout.py PATH --config baseline
    uv run python scripts/eval_heldout.py PATH --config final
    uv run python scripts/eval_heldout.py PATH_V2 --config shipped   (v2 baseline)

docs/plans/accuracy-phase.md, section 2 (frozen 2026-11-14), and ADR 0007:

- Runs exactly eval_flow.py's pipeline (run_case: full flow, cold, budget
  off) and scorer_v1 over the snapshot, with a FIXED now of
  2026-11-14T10:00:00+08:00 for every case. A "now" field in the file is
  not read.
- Prints only: the settings, the file's SHA-256 and case count, and the
  section 0 totals (counts). Never a per-case line, id, question or reply.
- Writes nothing to disk and uses no cache, unless --private-report PATH
  is given (below).
- At most two runs ever: --config baseline (done 2026-11-14) and
  --config final. Never in between, and never again: a later change is a
  v2 evaluated on a NEW held-out set (user, 2026-11-16).
- --config baseline is eval_flow.py's default path (newest first, and_v3,
  answer v1, no strip). --config final is archways_assistant.frozen.FINAL
  (the phone defaults): rank_v1, and_v4, strip_nf_v1, answer v1; retry and
  the excerpt window off. Its settings line adds those keys.

File format: JSON Lines, one case per line, every case over the snapshot
("data" may be omitted or "snapshot"):

    id                 string, unique
    question           string
    source_ids         list of snapshot row ids (strings); empty for a trap
    must_include       list of groups; each group is a non-empty list of
                       phrases, any one of which must be in the AI answer
                       (ignoring case); every group must match
    must_not_include   list of phrases that make an AI answer wrong
    expects_not_found  true for a trap (clean = no AI answer shown)
    optional: wrong_claims (list), wrong_rows (snapshot ids),
              superseded ({current: [...], old: [...]}),
              out_of_scope (bool), and notes (label, note, expected,
              category, english_twin, exclusion) that are never read.

v2 protocol (docs/plans/v2-improvements.md, approved 2026-11-17; ADR 0007
amendment): the v1 set is closed. A NEW file, written by the user for v2,
whose SHA-256 was recorded before any v2 fix (V2_SHA256). Each config
belongs to one protocol, so the date can't be mixed up:
- v1 configs: baseline, final (fixed now 2026-11-14T10:00:00+08:00).
- v2 configs: shipped = frozen.FINAL + window_v1 (archways_assistant.phone,
  what the app ships; the v2 BASELINE), fixed now 2026-11-17T10:00:00+08:00.
  The v2 FINAL config is added at the v2 freeze.
- A v2 config refuses any file but the recorded one, and a v1 config
  refuses the v2 file, before any model call (hash only; no value printed).
At most two v2 runs, by the user, same manual review.

A malformed file stops the run with the line number and the field name,
never a value.

--private-report PATH (the user's manual review; amendment of 2026-11-14):
writes one block per case (id, question, flags and reason codes, query
arguments, result ids, the final text the student would see) to PATH,
after the totals are printed. PATH must be outside the repository (checked
on the resolved path, ignoring case, before any model call) and must not
exist yet. The four printed lines are unchanged, and nothing says the
report was written. Only the user reads it; it never enters the repo, the
devlog or a chat. Without the option nothing is written.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
from eval_flow import (
    ANSWER_PROMPT,
    BASE_OPTIONS,
    KEEP_ALIVE,
    MATCHER,
    QUERY_N_PREDICT,
    QUERY_PROMPT,
    SNAPSHOT,
    format_extract,
    load_sources,
    model_digest,
    run_case,
    score_outcome,
    tree_is_dirty,
)
from probe_tool_call import SCHEMA_PATH, git_commit, ollama_version

from archways_assistant import assistant, phone
from archways_assistant.evalflow import (
    SCORER,
    CaseFileError,
    format_case,
    format_totals,
    load_cases,
    totals,
)
from archways_assistant.frozen import FINAL

FIXED_NOW = datetime.fromisoformat("2026-11-14T10:00:00+08:00")
FIXED_NOW_V2 = datetime.fromisoformat("2026-11-17T10:00:00+08:00")
# The v2 held-out file's SHA-256, recorded by the user with Get-FileHash on
# 2026-11-17, before any v2 fix was built.
V2_SHA256 = "ee9f407af9bd8899c1d247dcee10330dd1d2860b13e3c6f6482c81fd5839173c"
CONFIGS = ("baseline", "final", "shipped")
V2_CONFIGS = ("shipped",)
MODEL = "qwen3:0.6b"
REPO = Path(__file__).resolve().parents[1]


def config_run(name: str) -> tuple[Path, dict]:
    """(answer prompt, run_case keyword arguments) of a config."""
    if name == "baseline":
        return ANSWER_PROMPT, {}
    options = {
        "rank": FINAL.rank,
        "matcher": FINAL.matcher,
        "retry": FINAL.retry,
        "excerpt": FINAL.excerpt,
        "strip_nf": FINAL.strip_nf,
    }
    if name == "shipped":
        options["window"] = phone.FALLBACK
    return REPO / FINAL.answer_prompt, options


def fixed_now_for(name: str) -> datetime:
    return FIXED_NOW_V2 if name in V2_CONFIGS else FIXED_NOW


def check_protocol(name: str, data: bytes) -> None:
    """Exit unless the file belongs to the config's protocol (hash only)."""
    digest = hashlib.sha256(data).hexdigest()
    if name in V2_CONFIGS and digest != V2_SHA256:
        sys.exit("a v2 config runs only the recorded v2 held-out file (hash differs)")
    if name not in V2_CONFIGS and digest == V2_SHA256:
        sys.exit("this is the v2 held-out file: use a v2 config (the v1 set is closed)")


def private_report_path(value: str) -> Path:
    """The --private-report path, or exit: outside the repo, not existing."""
    path = Path(value).resolve()
    inside = os.path.normcase(str(path)), os.path.normcase(str(REPO))
    if inside[0] == inside[1] or inside[0].startswith(inside[1] + os.sep):
        sys.exit("--private-report must be outside the repository")
    if path.exists():
        sys.exit("--private-report must not exist yet")
    if not path.parent.is_dir():
        sys.exit("--private-report: the folder does not exist")
    return path


def write_private_report(path: Path, blocks: list[str]) -> None:
    """The only write in this script (accuracy-phase.md, 2026-11-14 amendment)."""
    with path.open("x", encoding="utf-8", newline="\n") as report:
        report.write("\n\n".join(blocks) + "\n")


def report_block(case: dict, record: dict, line: str) -> str:
    return "\n".join(
        [
            f"=== {case['id']} ===",
            f"question: {case['question']}",
            f"score: {line}",
            f"query arguments: {json.dumps(record['arguments'], ensure_ascii=False)}",
            "final text:",
            record["text"],
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--config", required=True, choices=CONFIGS)
    parser.add_argument("--private-report", metavar="PATH")
    args = parser.parse_args()
    report = None
    if args.private_report is not None:
        report = private_report_path(args.private_report)

    try:
        data = args.path.read_bytes()
    except OSError:
        sys.exit("cannot read the held-out file")
    check_protocol(args.config, data)
    fixed_now = fixed_now_for(args.config)
    rows = load_sources()["snapshot"]
    by_id = {row["id"]: row for row in rows}
    offices = {row["office"] for row in rows}
    try:
        cases = load_cases(
            args.path,
            {"snapshot": set(by_id)},
            fixed_now=fixed_now,
            default_data="snapshot",
        )
    except CaseFileError as error:
        sys.exit(f"held-out file: {error}")
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    answer_prompt, run_options = config_run(args.config)
    prompts = {
        "query": QUERY_PROMPT.read_text(encoding="utf-8"),
        "answer": answer_prompt.read_text(encoding="utf-8"),
    }

    with httpx.Client(timeout=600, trust_env=False) as client:
        settings = {
            "config": args.config,
            "fixed_now": fixed_now.isoformat(),
            "ollama": ollama_version(client),
            "model": MODEL,
            "model_digest": model_digest(client, MODEL),
            "commit": git_commit(),
            "tree_dirty": tree_is_dirty(),
            "scorer": SCORER,
            "matcher": MATCHER,
            "budget": "off",
            "options": BASE_OPTIONS,
            "keep_alive": KEEP_ALIVE,
            "n_predict": {
                "query": QUERY_N_PREDICT,
                "answer": assistant.ANSWER_N_PREDICT,
            },
            "prompts": {
                "query": [
                    QUERY_PROMPT.name,
                    hashlib.sha256(QUERY_PROMPT.read_bytes()).hexdigest(),
                ],
                "answer": [
                    answer_prompt.name,
                    hashlib.sha256(answer_prompt.read_bytes()).hexdigest(),
                ],
            },
            "snapshot_sha256": hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(),
        }
        if run_options:
            settings.update(run_options)
        print(f"settings: {json.dumps(settings, ensure_ascii=True)}")
        print(
            f"held-out file sha256 {hashlib.sha256(data).hexdigest()}  cases {len(cases)}"
        )
        scores, blocks = [], []
        for number, case in enumerate(cases, start=1):
            try:
                record = run_case(
                    client, MODEL, case, prompts, rows, contract, **run_options
                )
                # An extract (v2 fix (d)) is scored as an answer.
                score = score_outcome(
                    case,
                    record["path"],
                    record["text"],
                    record["results"],
                    by_id,
                    offices,
                )
                scores.append(score)
                if report is not None:
                    blocks.append(report_block(case, record, format_case(score)))
            except Exception as error:  # noqa: BLE001 - never print a value
                sys.exit(
                    f"case number {number} failed ({type(error).__name__}); no totals"
                )
    print(format_totals("HELD-OUT", totals(scores)))
    line = format_extract("HELD-OUT", scores)
    if line:
        print(line)
    if report is not None:
        write_private_report(report, blocks)


if __name__ == "__main__":
    main()
