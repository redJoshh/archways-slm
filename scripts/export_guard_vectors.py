"""Export guard parity vectors to tests/vectors/guard_vectors.json.

Usage:
    uv run python scripts/export_guard_vectors.py            # rebuild from sources
    uv run python scripts/export_guard_vectors.py --refresh  # recompute expected only

Each vector holds the guard's inputs (question, results as the guard sees
them, forbidden titles, the model reply, and the case's now for context;
the guard never reads it) and the Python guard's output: fired, the
reason codes and the final text shown. python_reasons is informational.
guard-ts must match fired, codes and text exactly
(tests/test_guard_vectors.py checks the Python side).

Sources:
- unit: the guard-related cases in tests/test_e2escore.py.
- edge: hand-written parity cases (Unicode, spaces, dates, posted_at).
- phone: replies from the phones quoted word for word in docs/devlog.md.
- run: every reply in the saved probe runs (runs/, gitignored), as logged
  and with the probe's " | " line joins turned back into newlines
  (scripts/saved_runs.py).

A rebuild needs runs/. After a guard change, --refresh recomputes
expected for the inputs already in the file, so it works without runs/.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from probe_end_to_end import load_cases
from saved_runs import is_probe_run, parse, restored_reply

from archways_assistant.e2escore import (
    FALLBACK_HEADER,
    GUARD_SPACES,
    LAST_RESORT_MESSAGE,
    NON_ASCII_DIGIT_RANGES,
    guard,
)
from archways_assistant.fakebackend import is_visible, to_announcement

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "vectors" / "guard_vectors.json"
SEED = ROOT / "data" / "seed" / "announcements.json"
FORMAT = "archways guard vectors v1"


def load_unit_tests():
    path = ROOT / "tests" / "test_e2escore.py"
    spec = importlib.util.spec_from_file_location("unit_e2escore", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def params(test, position=0):
    """The first argument of each parametrize case of a test function."""
    (mark,) = [m for m in test.pytestmark if m.name == "parametrize"]
    values = mark.args[1]
    return [v[position] if isinstance(v, tuple) else v for v in values]


def vector(source, reply, results, question, forbidden=(), now=None):
    return {
        "sources": [source],
        "input": {
            "question": question,
            "results": results,
            "forbidden": list(forbidden),
            "reply": reply,
            "now": now,
        },
    }


def unit_vectors():
    t = load_unit_tests()
    results, dec6 = t.RESULTS, t.DEC_6_RESULTS
    drop_q = "When can I drop subjects?"
    out = []
    for text in params(t.test_claims):
        out.append(vector("unit:test_claims", text, results, drop_q))
    for name in (
        "test_supported_replies_have_no_unsupported_claims",
        "test_unsupported_claims",
    ):
        for reply in params(getattr(t, name)):
            out.append(vector(f"unit:{name}", reply, results, drop_q))
    for reply in params(t.test_dates_split_by_non_ascii_spaces_are_still_dates):
        out.append(
            vector(
                "unit:test_dates_split_by_non_ascii_spaces_are_still_dates",
                reply,
                dec6,
                "When?",
            )
        )
    bad_dates = params(t.test_posted_date_rejects_everything_else)
    good_dates = params(t.test_posted_date_reads_the_contract_format)
    for name, values in (
        ("test_posted_date_reads_the_contract_format", good_dates),
        ("test_posted_date_rejects_everything_else", bad_dates),
    ):
        for posted in values:
            rows = [{**results[0], "posted_at": posted}]
            out.append(vector(f"unit:{name}", "Due November 6.", rows, "When?"))

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    ann_004 = next(row for row in seed if row["id"] == "ann-004")
    e2e_003 = [
        {**results[0], "title": ann_004["title"], "excerpt": ann_004["body"][:500]}
    ]
    inline = [
        (
            "test_posted_timestamps_do_not_support_claims",
            "Room 10.",
            results,
            drop_q,
            [],
        ),
        (
            "test_fallback_uses_only_titles_and_posted_dates",
            "Room 10.",
            results,
            drop_q,
            [],
        ),
        (
            "test_guard_passes_a_supported_reply_through",
            "The last day is November 13.",
            results,
            "When?",
            ["Secret Draft"],
        ),
        (
            "test_guard_replaces_an_unsupported_reply_with_the_fallback",
            "The last day is November 6.",
            results,
            "When?",
            [],
        ),
        (
            "test_guard_fires_on_filtered_row_text",
            "See the secret draft notice.",
            results,
            "When?",
            ["Secret Draft"],
        ),
        (
            "test_todays_date_is_not_allowed",
            "Today, November 2, forms are accepted until 4:00 PM.",
            results,
            drop_q,
            [],
        ),
        (
            "test_dates_and_numbers_in_the_question_are_allowed",
            "Yes, on November 2 at 8.",
            results,
            "Is the office open on November 2 at 8?",
            [],
        ),
        (
            "test_rescore_gemma_e2e_003_reply",
            (
                "The deadline for submitting accreditation documents is November 2nd.  "
                "Complete all required documents before then.  The required documents "
                "include a constitution, by-laws, officer signatures, adviser's letter, "
                "financial report, proposed calendar, and certificate of good standing."
            ),
            e2e_003,
            "When is the deadline for submitting org accreditation documents?",
            [],
        ),
        (
            "test_long_s_month_does_not_crash_and_its_number_is_checked",
            "\u017fep 5",
            results,
            "When?",
            [],
        ),
        (
            "test_non_ascii_digit_fails_closed",
            "The last day is November \uff17.",
            [{**results[0], "excerpt": "The last day is November 7."}],
            "When?",
            [],
        ),
        (
            "test_time_with_a_narrow_no_break_space_does_not_fire",
            "It starts at 4:00\u202fPM.",
            dec6,
            "When?",
            [],
        ),
        (
            "test_guard_codes_name_every_reason_in_order",
            "Secret Draft: November 6, room 7, day \u0665.",
            results,
            "When?",
            ["Other", "secret draft", "SECRET DRAFT"],
        ),
        (
            "test_guard_codes_are_empty_when_it_does_not_fire",
            "The last day is November 13.",
            results,
            "When?",
            [],
        ),
        ("test_number_codes_are_canonical", "Call 007 or 000.", results, "When?", []),
        (
            "test_fired_guard_with_an_unreadable_posted_at_gives_the_last_resort",
            "The last day is November 6.",
            [{**results[0], "posted_at": "2026-10-29"}],
            "When?",
            [],
        ),
        (
            "test_unfired_guard_never_reads_posted_at",
            "The last day is November 13.",
            [{**results[0], "posted_at": "not a date"}],
            "When?",
            [],
        ),
    ]
    for name, reply, rows, question, forbidden in inline:
        out.append(vector(f"unit:{name}", reply, rows, question, forbidden))
    return out


def edge_vectors():
    base = {
        "id": "edge-1",
        "title": "Revised Deadline for Dropping of Subjects",
        "excerpt": "Forms are due November 13, 2026 until 4:00 PM. The fee is \u20b1500.",
        "office": "Office of the Registrar",
        "priority": "HIGH",
        "year_level": None,
        "posted_at": "2026-10-29T10:00:00+08:00",
    }
    dec6 = {
        **base,
        "id": "edge-2",
        "title": "Career Fair",
        "excerpt": "The fair is on December 6 from 4:00 PM.",
        "posted_at": "2026-10-23T09:00:00+08:00",
    }
    one, two = [base], [base, dec6]
    q = "When is the deadline?"
    replies = [
        # Case folding and month look-alikes.
        "\u017fep 5",
        "\u017fEPT 13",
        "Sept 13",
        "SEPT 13",
        "NOV. 13TH",
        "nov.13",
        "Apr\u0131l 13",
        "Apr\u0130l 13",
        "\u212a 13",
        "may 2",
        "MAY 13",
        # Non-ASCII digits.
        "Nov \u0665",
        "November \uff11\uff13",
        "\U0001d7d3 November",
        "Nov 13 (\u0967\u0969)",
        # Spaces that are not in GUARD_SPACES.
        "November\ufeff6",
        "November\x1c6",
        "November\u200b6",
        "November\t6",
        "November\r\n6",
        # Dates, numbers and punctuation.
        "Due 12:00 NN on Nov 13.",
        "Due Nov 13.",
        "Due the 13th.",
        "Due the 13th of Nov.",
        "Due 13 November 2026.",
        "Open Nov 16\u201328.",
        "Pay \u20b1500 by 4:00 PM.",
        "\u201cNov 13,\u201d she said \u2019til 4:00.",
        "Due 2026-11-13.",
        "Due 2026-13-45.",
        "Due Nov 32.",
        "Due Nov 00.",
        "Due Nov 6th, 2026.",
        "Code 007.",
        "Call 123456789012345678901234567890.",
        "Line one.\nNov 13\nline three.",
        "",
        "   ",
    ]
    out = [vector("edge:text", r, one, q) for r in replies]
    out += [vector("edge:text-two-rows", r, two, q) for r in replies]
    for ch in GUARD_SPACES:
        out.append(vector(f"edge:space-U+{ord(ch):04X}", f"November{ch}6", two, q))
        out.append(
            vector(f"edge:space-U+{ord(ch):04X}", f"Nov{ch}13 at 4:00{ch}PM", one, q)
        )
    out.append(vector("edge:no-results", "Due Nov 13.", [], q))
    out.append(vector("edge:question-support", "Yes, Nov 6.", one, "Is it on Nov 6?"))
    forbidden_cases = [
        ("See the Secret Draft.", ["Secret Draft", "Secret Draft"]),
        ("Anything at all.", [""]),
        ("SECRET DRAFT here.", ["secret draft"]),
        ("Read the dean\u2019s list.", ["Dean\u2019s List"]),
        ("A\xd1O NUEVO.", ["A\xf1o Nuevo"]),
        ("Nothing filtered.", ["Hidden", "Other"]),
    ]
    for reply, forbidden in forbidden_cases:
        out.append(vector("edge:forbidden", reply, one, q, forbidden))
    return out


def phone_vectors():
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in seed}
    # e2e-009's answer call (runs/gate1_prompt.txt): ann-015, ann-001, ann-025.
    results = [to_announcement(by_id[i]) for i in ("ann-015", "ann-001", "ann-025")]
    question = "When will the student portal be down for maintenance?"
    now = "2026-11-02T10:00:00+08:00"
    cold = (
        "The student portal is unavailable on November 7th from 10:00 PM to 2:00 AM. "
        "Online enrollment for the second term begins on November 9th and closes on "
        "November 20th. "
    )
    replies = [
        (
            "phone:redmi-gemma3-cold",
            cold + "New research databases are available through the student portal.",
        ),
        # The devlog gives the warm reply as the cold one with a new last sentence.
        (
            "phone:redmi-gemma3-warm",
            cold + "New online research databases are available starting November 9th.",
        ),
        (
            "phone:nothing-gemma3-cold",
            (
                "The student portal will be unavailable on November 7th, 2026, from "
                "10:00 PM to 2:00 AM. Online enrollment for the second term begins on "
                "November 9th, 2026, and closes on November 20th, 2026. Access to new "
                "research databases will be available starting November 9th, 2026."
            ),
        ),
        (
            "phone:redmi-qwen3-0.6b",
            (
                "The student portal will be unavailable on November 7, 2026, from "
                "10:00 PM until 2:00 AM the next day for maintenance."
            ),
        ),
    ]
    forbidden = [r["title"] for r in seed if not is_visible(r, _now(now))]
    return [vector(s, r, results, question, forbidden, now) for s, r in replies]


def _now(text):
    from datetime import datetime

    return datetime.fromisoformat(text)


def run_vectors(report):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in seed}
    files = sorted(p for p in (ROOT / "runs").glob("*.txt") if is_probe_run(p))
    if not files:
        sys.exit("runs/ has no probe runs; use --refresh to update expected only")
    cases = {}
    out = []
    agree = disagree = 0
    for path in files:
        for rec in parse(path):
            if not rec.answered or rec.reply is None:
                continue
            if rec.cases_file not in cases:
                loaded = load_cases(ROOT / rec.cases_file)
                cases[rec.cases_file] = {c["id"]: c for c in loaded}
            case = cases[rec.cases_file][rec.case_id]
            if case["question"] != rec.question:
                sys.exit(f"{path.name} {rec.case_id}: question differs from the case")
            results = [to_announcement(by_id[i]) for i in rec.ids]
            forbidden = [r["title"] for r in seed if not is_visible(r, case["now"])]
            now = case["now"].isoformat()
            source = f"run:{path.name}:{rec.case_id}"
            restored = restored_reply(rec.reply)
            out.append(vector(source, rec.reply, results, rec.question, forbidden, now))
            if restored != rec.reply:
                out.append(
                    vector(
                        source + ":newlines",
                        restored,
                        results,
                        rec.question,
                        forbidden,
                        now,
                    )
                )
            g = guard(restored, results, rec.question, forbidden)
            line = f"fired ({'; '.join(g.reasons)})" if g.fired else "not fired"
            if line == rec.guard_line:
                agree += 1
            else:
                disagree += 1
                report.append(f"  {source}: logged {rec.guard_line!r}, now {line!r}")
    report.insert(
        0,
        f"runs: {len(files)} files; guard line now vs logged: "
        f"{agree} agree, {disagree} differ",
    )
    return out


def expected(inp):
    g = guard(inp["reply"], inp["results"], inp["question"], inp["forbidden"])
    return {"fired": g.fired, "codes": list(g.codes), "text": g.text}, list(g.reasons)


def spec():
    return {
        "guard_spaces": [ord(ch) for ch in GUARD_SPACES],
        "non_ascii_digit_ranges": [list(r) for r in NON_ASCII_DIGIT_RANGES],
        "fallback_header": FALLBACK_HEADER,
        "last_resort_message": LAST_RESORT_MESSAGE,
    }


def finish(vectors):
    for number, v in enumerate(vectors, start=1):
        v["id"] = f"v{number:04d}"
        v["expected"], v["python_reasons"] = expected(v["input"])
    ordered = [
        {k: v[k] for k in ("id", "sources", "input", "expected", "python_reasons")}
        for v in vectors
    ]
    doc = {
        "format": FORMAT,
        "about": "Guard parity vectors; see scripts/export_guard_vectors.py.",
        "spec": spec(),
        "vectors": ordered,
    }
    text = json.dumps(doc, ensure_ascii=True, indent=1) + "\n"
    OUT.write_bytes(text.encode("ascii"))
    return ordered


def dedupe(vectors):
    seen = {}
    for v in vectors:
        key = json.dumps(v["input"], sort_keys=True)
        if key in seen:
            if v["sources"][0] not in seen[key]["sources"]:
                seen[key]["sources"] += v["sources"]
        else:
            seen[key] = v
    return list(seen.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.refresh:
        doc = json.loads(OUT.read_text(encoding="utf-8"))
        vectors = finish(doc["vectors"])
        print(f"refreshed {len(vectors)} vectors")
        return
    report = []
    vectors = dedupe(
        unit_vectors() + edge_vectors() + phone_vectors() + run_vectors(report)
    )
    vectors = finish(vectors)
    kinds = {}
    for v in vectors:
        for s in {s.split(":", 1)[0] for s in v["sources"]}:
            kinds[s] = kinds.get(s, 0) + 1
    fired = sum(v["expected"]["fired"] for v in vectors)
    print(f"wrote {len(vectors)} vectors ({fired} fired) to {OUT.relative_to(ROOT)}")
    print("vectors per source type:", kinds)
    print("\n".join(report))


if __name__ == "__main__":
    main()
