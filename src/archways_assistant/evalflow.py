"""scorer_v1: the accuracy-phase metrics, and the case loader for eval_flow.py.

The rules are docs/plans/accuracy-phase.md, section 0 (frozen 2026-11-14).
This module only implements them; a change to a rule is scorer_v2, never an
edit here that changes a result.

Per case, from the flow's final path and text:

- The AI answer is the text between ANSWER_LABEL and the results list, on
  the "answer" path only. must_include is checked there, never in the list.
- The shown list is the result ids, on every path whose text is the
  results list (no list: not_found and the last-resort paths).
- A wrong AI answer has any of: a must_not_include phrase, a wrong_claims
  phrase, an unsupported date or number, a wrong-row date or number, a
  stale date, or a wrong entity (entity_v1: an office name, from the set of
  office values of the case's data source, that is not a source row's
  office and is not in a source row's title or text).
- Answerable (expects_not_found false): correct = every must_include group
  in the AI answer and not wrong; helpful = not wrong and (correct or at
  least one source row shown); coverage = source rows shown / source rows.
- Trap (expects_not_found true): clean = no AI answer shown; an
  "unrelated list" is a clean trap with a non-empty shown list. A trap's
  answer-path reply is never correct.
- Unsafe = a wrong AI answer, on any case.
- out_of_scope cases are scored on Unsafe only.

Pure functions, no I/O except load_cases(). Loader errors name the line
and the field, never a value, so a held-out file's text is never printed.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from archways_assistant.assistant import (
    ANSWER_LABEL,
    ANSWER_LABEL_SEPARATOR,
    ANSWER_LIST_SEPARATOR,
    LAST_RESORT_MESSAGE,
    safe_results_list,
)
from archways_assistant.e2escore import (
    NOT_FOUND_MESSAGE,
    missing_groups,
    present,
    stale_problems,
    supported,
    unsupported_claims,
    wrong_row_claims,
    wrong_rows_for,
)

SCORER = "scorer_v1"
DATA_SOURCES = ("seed", "snapshot")

REQUIRED = {
    "id": str,
    "question": str,
    "source_ids": list,
    "must_include": list,
    "must_not_include": list,
    "expects_not_found": bool,
}
OPTIONAL = {
    "now": str,
    "data": str,
    "wrong_claims": list,
    "wrong_rows": list,
    "superseded": dict,
    "out_of_scope": bool,
}
# Notes for people, any JSON value; never read by the scorer.
NOTES = frozenset(
    {"label", "note", "expected", "english_twin", "exclusion", "category"}
)


class CaseFileError(ValueError):
    """A malformed case file. The message names a line and a field only."""


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def load_cases(
    path: Path,
    known_ids: dict[str, set[str]],
    fixed_now: datetime | None = None,
    default_data: str = "seed",
) -> list[dict]:
    """Read a JSONL case file and check it against the data sources.

    known_ids maps each data source to its row ids. With fixed_now, every
    case gets that instant and a "now" field is not read (held-out files);
    otherwise "now" is required. Raises CaseFileError naming the line and
    the field, never a value.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        raise CaseFileError("cannot read the cases file as UTF-8") from None
    cases = []
    seen = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"line {number}"
        try:
            case = json.loads(line)
        except ValueError:
            raise CaseFileError(f"{where}: not valid JSON") from None
        if not isinstance(case, dict):
            raise CaseFileError(f"{where}: not a JSON object")
        for position, field in enumerate(case, start=1):
            if field not in REQUIRED and field not in OPTIONAL and field not in NOTES:
                raise CaseFileError(f"{where}: unknown field (key number {position})")
        for field, kind in REQUIRED.items():
            if not isinstance(case.get(field), kind):
                raise CaseFileError(
                    f"{where}: {field!r} is missing or not a {kind.__name__}"
                )
        for field, kind in OPTIONAL.items():
            if field in case and not isinstance(case[field], kind):
                raise CaseFileError(f"{where}: {field!r} is not a {kind.__name__}")
        if not case["id"]:
            raise CaseFileError(f"{where}: 'id' is empty")
        if case["id"] in seen:
            raise CaseFileError(f"{where}: duplicate 'id'")
        seen.add(case["id"])
        groups = case["must_include"]
        if not all(_strings(group) and group for group in groups):
            raise CaseFileError(
                f"{where}: 'must_include' must be non-empty string lists"
            )
        for field in ("source_ids", "must_not_include", "wrong_claims", "wrong_rows"):
            if not _strings(case.get(field, [])):
                raise CaseFileError(f"{where}: {field!r} must be a list of strings")
        superseded = case.get("superseded")
        if superseded is not None and not (
            set(superseded) == {"current", "old"}
            and all(_strings(superseded[key]) for key in superseded)
        ):
            raise CaseFileError(f"{where}: 'superseded' must be {{current, old}}")
        data = case.get("data", default_data)
        if data not in known_ids:
            raise CaseFileError(f"{where}: 'data' is not one of {sorted(known_ids)}")
        case["data"] = data
        ids = known_ids[data]
        for field in ("source_ids", "wrong_rows"):
            if not set(case.get(field, [])) <= ids:
                raise CaseFileError(f"{where}: {field!r} names a row not in {data!r}")
        if not case["expects_not_found"] and not case["source_ids"]:
            raise CaseFileError(f"{where}: an answerable case needs 'source_ids'")
        if fixed_now is not None:
            case["now"] = fixed_now
        else:
            try:
                now = datetime.fromisoformat(case.get("now", ""))
            except (TypeError, ValueError):
                raise CaseFileError(f"{where}: 'now' is missing or not ISO") from None
            if now.tzinfo is None:
                raise CaseFileError(f"{where}: 'now' needs a UTC offset")
            case["now"] = now
        cases.append(case)
    if not cases:
        raise CaseFileError("the cases file has no cases")
    return cases


def split_final_text(
    path: str, text: str, results: list[dict]
) -> tuple[str | None, list[str]]:
    """(the AI answer or None, the shown result ids) of a flow final text."""
    listed = safe_results_list(results) if results else None
    if path == "answer":
        head = ANSWER_LABEL + ANSWER_LABEL_SEPARATOR
        tail = ANSWER_LIST_SEPARATOR + (listed or "")
        if listed is None or not (text.startswith(head) and text.endswith(tail)):
            raise ValueError("an answer-path text without its label and list")
        return text[len(head) : len(text) - len(tail)], [r["id"] for r in results]
    if listed is not None and text == listed:
        return None, [r["id"] for r in results]
    if text in (LAST_RESORT_MESSAGE, NOT_FOUND_MESSAGE):
        return None, []
    raise ValueError(f"a {path} text that is neither the list nor a fixed message")


def entity_problems(
    answer: str, offices: set[str], source_rows: list[dict]
) -> list[str]:
    """entity_v1: office names in the answer that the source rows don't support."""
    own = {row["office"].lower() for row in source_rows}
    texts = [f"{row['title']}\n{row['body']}".lower() for row in source_rows]
    problems = []
    for office in sorted(offices):
        name = office.lower()
        pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
        if not re.search(pattern, answer.lower()):
            continue
        if name in own or any(re.search(pattern, text) for text in texts):
            continue
        problems.append(f"entity:{office}")
    return problems


@dataclass(frozen=True)
class CaseScore:
    id: str
    path: str
    result_ids: tuple[str, ...]
    shown_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    trap: bool
    out_of_scope: bool
    answered: bool  # an AI answer was shown
    wrong: tuple[str, ...]  # reason codes; empty = not wrong
    missing: tuple[str, ...]  # must_include groups missing (first phrase each)
    correct: bool
    helpful: bool | None  # None for traps and out-of-scope cases
    clean: bool | None  # None for answerable cases
    unrelated_list: bool
    coverage: tuple[int, int]  # (source rows shown, source rows), answerable only

    @property
    def unsafe(self) -> bool:
        return bool(self.wrong)

    def places(self) -> list[str]:
        """Each source row's place in the results (1-based) or '-'."""
        return [
            f"{sid}@{self.result_ids.index(sid) + 1}"
            if sid in self.result_ids
            else f"{sid}@-"
            for sid in self.source_ids
        ]


def score_case(
    case: dict,
    path: str,
    text: str,
    results: list[dict],
    rows_by_id: dict[str, dict],
    offices: set[str],
) -> CaseScore:
    answer, shown = split_final_text(path, text, results)
    sources = list(case["source_ids"])
    source_rows = [rows_by_id[sid] for sid in sources]
    trap = case["expects_not_found"]
    out_of_scope = case.get("out_of_scope", False)
    result_ids = [r["id"] for r in results]
    wrong: list[str] = []
    missing: list[str] = []
    if answer is not None:
        wrong += [f"contains:{p}" for p in present(answer, case["must_not_include"])]
        wrong += [
            f"wrong_claim:{p}" for p in present(answer, case.get("wrong_claims", []))
        ]
        wrong += [
            f"unsupported:{c}"
            for c in unsupported_claims(answer, supported(results, case["question"]))
        ]
        wrong_ids = wrong_rows_for(
            named=case.get("wrong_rows", []), retrieved=result_ids, sources=sources
        )
        wrong += [
            f"wrong_row:{c}"
            for c in wrong_row_claims(
                answer,
                [rows_by_id[i] for i in wrong_ids],
                source_rows,
                case["question"],
            )
        ]
        wrong += [
            f"stale:{p}"
            for p in stale_problems(answer, case.get("superseded"))
            if p.startswith("stale ")
        ]
        wrong += entity_problems(answer, offices, source_rows)
        missing = [group[0] for group in missing_groups(answer, case["must_include"])]
    answered = answer is not None
    correct = answered and not trap and not missing and not wrong
    shown_sources = [sid for sid in sources if sid in shown]
    helpful = clean = None
    if not out_of_scope:
        if trap:
            clean = not answered
        else:
            helpful = not wrong and (correct or bool(shown_sources))
    return CaseScore(
        id=case["id"],
        path=path,
        result_ids=tuple(result_ids),
        shown_ids=tuple(shown),
        source_ids=tuple(sources),
        trap=trap,
        out_of_scope=out_of_scope,
        answered=answered,
        wrong=tuple(wrong),
        missing=tuple(missing),
        correct=correct,
        helpful=helpful,
        clean=clean,
        unrelated_list=bool(clean) and bool(shown),
        coverage=(len(shown_sources), len(sources)) if not trap else (0, 0),
    )


def totals(scores: list[CaseScore]) -> dict:
    """The section 0 counts for a group of scored cases."""
    scored = [s for s in scores if not s.out_of_scope]
    answerable = [s for s in scored if not s.trap]
    traps = [s for s in scored if s.trap]
    on_answer = [s for s in scored if s.answered]
    return {
        "cases": len(scores),
        "helpful": (sum(s.helpful for s in answerable), len(answerable)),
        "ai_correct": (sum(s.correct for s in on_answer), len(on_answer)),
        "unsafe": (sum(s.unsafe for s in scores), len(scores)),
        "traps_clean": (sum(s.clean for s in traps), len(traps)),
        "traps_unrelated_list": (sum(s.unrelated_list for s in traps), len(traps)),
        "coverage": (
            sum(s.coverage[0] for s in answerable),
            sum(s.coverage[1] for s in answerable),
        ),
        "out_of_scope": len(scores) - len(scored),
        "paths": dict(sorted(Counter(s.path for s in scores).items())),
    }


def format_totals(name: str, counts: dict) -> str:
    def frac(pair: tuple[int, int]) -> str:
        return f"{pair[0]}/{pair[1]}"

    paths = " ".join(f"{p}={n}" for p, n in counts["paths"].items())
    return (
        f"{name}: cases {counts['cases']}  helpful {frac(counts['helpful'])}  "
        f"ai_correct {frac(counts['ai_correct'])}  unsafe {frac(counts['unsafe'])}  "
        f"traps_clean {frac(counts['traps_clean'])}  "
        f"traps_unrelated_list {frac(counts['traps_unrelated_list'])}  "
        f"coverage {frac(counts['coverage'])}  out_of_scope {counts['out_of_scope']}\n"
        f"  paths: {paths}"
    )


def format_case(score: CaseScore) -> str:
    """One per-case line: ids, flags and reason codes (no question or reply)."""
    if score.out_of_scope:
        verdict = "OUT_OF_SCOPE"
    elif score.trap:
        verdict = "CLEAN" if score.clean else "NOT_CLEAN"
    else:
        verdict = "HELPFUL" if score.helpful else "UNHELPFUL"
    flags = [verdict]
    if score.answered:
        flags.append("AI_CORRECT" if score.correct else "AI_NOT_CORRECT")
    if score.unsafe:
        flags.append("UNSAFE")
    if score.unrelated_list:
        flags.append("UNRELATED_LIST")
    codes = [*score.wrong, *(f"missing:{m}" for m in score.missing)]
    cover = "" if score.trap else f"  coverage {score.coverage[0]}/{score.coverage[1]}"
    return (
        f"{score.id}: {score.path}  results {list(score.result_ids)}  "
        f"sources {score.places()}{cover}  {' '.join(flags)}"
        + (f"  [{'; '.join(codes)}]" if codes else "")
    )
