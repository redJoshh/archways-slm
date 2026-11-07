"""Write tests/vectors/feed_vectors.json: parity vectors for the on-phone search.

Usage: uv run python scripts/export_feed_vectors.py [--check]

ADR 0006: the assistant searches the student's feed on the phone. These
vectors pin what assistant-ts must do, from the Python reference only:
- plain_text: excerpt.plain_text() on the hand-worked cases of
  tests/test_excerpt.py plus CMS-like and edge HTML
- cut: the excerpt cut to EXCERPT_CHARS code points
- published_at: feedindex.parse_published_at()
- rows: feedindex.feed_row() then fakebackend.to_announcement() on feed
  details (or null: the item is skipped)
- search: feedindex.search_feed() (and_v3) over feed details built from the
  visible rows of tests/vectors/search_vectors_and_v3.json (whose rows
  include the and_v1 and and_v2 rows), plus synthetic rows for the flow
  queries and Unicode edges, for every query of the three search vector
  files, the flow-test queries and the edge queries.

All announcement text here is synthetic (the seed vectors' rows and rows
written for this file); the flow queries are the keywords qwen3:0.6b wrote,
never real announcement text. Deterministic; --check exits 1 if the
committed file differs. ASCII-only JSON with LF line endings.
"""

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

from archways_assistant.excerpt import plain_text
from archways_assistant.fakebackend import (
    EXCERPT_CHARS,
    InvalidArguments,
    plural_alternative,
    to_announcement,
)
from archways_assistant.feedindex import feed_row, parse_published_at, search_feed

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "vectors" / "feed_vectors.json"
VECTOR_FILES = ("search_vectors", "search_vectors_and_v2", "search_vectors_and_v3")
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text(
        encoding="utf-8"
    )
)
# The queries qwen3:0.6b wrote cold for the 10 flow-test questions
# (2026-11-07, local-data/flow_test.json); keywords only.
FLOW_QUERIES = [
    {"query": "office", "days": 30},
    {"query": "foundation anniversary", "days": 30},
    {"query": "emergency water service interruption", "days": 30},
    {"query": "general weight average", "days": 30},
    {"query": "Paskuhan 2026", "days": 30},
    {"query": "uniforms", "days": 30},
    {"query": "remote work", "days": 30},
    {"query": "single-use plastics", "days": 30},
    {"query": "dropping forms", "days": 30},
    {"query": "halloween costume party", "days": 30},
    {"query": "drop forms", "days": 30},
]
PLURAL_WORDS = [
    "forms",
    "uniforms",
    "exams",
    "rules",
    "class",
    "classes",
    "campus",
    "basis",
    "thesis",
    "fees",
    "news",
    "staff's",
    "x-rays",
    "(forms",
    "forms)",
    "cafés",
    "niños",
    "𝐀𝐀𝐀s",
    "𝐀bcs",
    "abc𝐀s",
    "a٣bcs",
    "12345s",
    "_abcs",
    "s",
    "ss",
    "sssss",
    "éééés",
    "abcd²s",
]
EDGE_QUERIES = [
    {"query": "drop forms"},
    {"query": "drop forms"},
    {"query": "drop\u0085forms"},
    {"query": "cafés"},
    {"query": "CAFÉS"},
    {"query": "niños"},
    {"query": "forms", "days": 1},
    {"query": "forms", "days": 30, "limit": 2},
    {"query": "the of"},
    {"query": "kapag forms"},
    {"query": "campus"},
    {"query": "thesis"},
]
# Synthetic rows (invented text) for the flow queries and Unicode edges:
# (id, title, body HTML, office, priority, publishedAt).
SYNTHETIC = [
    (
        901,
        "Office Hours Update",
        "<p>The <b>registrar's office</b> opens at 8&nbsp;AM.</p>",
        "Office of the Registrar",
        "NORMAL",
        "2026-11-01T08:00:00+08:00",
    ),
    (
        902,
        "Foundation Anniversary Mass",
        "<p>Join the foundation anniversary Mass at the field.</p>",
        "Campus Ministry",
        "HIGH",
        "2026-10-31T09:00:00+08:00",
    ),
    (
        903,
        "Emergency Water Service Interruption",
        "<p>Emergency water service interruption in Building A until 3:00&nbsp;PM.</p>",
        "Facilities",
        "HIGH",
        "2026-10-30T07:00:00+08:00",
    ),
    (
        904,
        "General Weighted Average Reminder",
        "<p>The general weighted average is computed per term.</p>",
        "Registrar",
        "NORMAL",
        "2026-10-29T10:00:00+08:00",
    ),
    (
        905,
        "Paskuhan 2026 Schedule",
        "<ul><li>Paskuhan 2026</li><li>Gates open at 5 PM</li></ul>",
        "Student Affairs",
        "NORMAL",
        "2026-10-28T10:00:00+08:00",
    ),
    (
        906,
        "Remote Work Advisory",
        "<p>Employees shift to remote work on Friday.</p>",
        "Human Resources",
        "NORMAL",
        "2026-10-27T10:00:00+08:00",
    ),
    (
        907,
        "Single-Use Plastics Ban",
        "<p>Single-use plastics &amp; styrofoam are banned.</p>",
        "Sustainability",
        "HIGH",
        "2026-10-26T12:00:00+08:00",
    ),
    (
        908,
        "Dropping Period",
        "<p>Submit dropping forms at the dean's office.</p>",
        "Registrar",
        "NORMAL",
        "2026-10-26T11:00:00+08:00",
    ),
    (
        909,
        "Café Reopening",
        "<p>The campus café reopens on Monday.</p>",
        "Auxiliary Services",
        "NORMAL",
        "2026-11-01T07:00:00Z",
    ),
    (
        910,
        "Niño Festival",
        "<p>The Santo Niño procession starts at the plaza.</p>",
        "Campus Ministry",
        "NORMAL",
        "2026-10-31T10:00:00",
    ),
    # No whole-word "form": followed by a letter (U+1D400, astral) or a
    # decimal digit (U+0663).
    (
        911,
        "Math Note",
        "<p>form\U0001d400 and form٣ only.</p>",
        "Mathematics",
        "NORMAL",
        "2026-10-30T10:00:00+08:00",
    ),
    # Only occurrence preceded by U+1D400 (an astral letter): no match.
    (
        914,
        "Astral Note",
        "<p>Only \U0001d400form here.</p>",
        "Mathematics",
        "NORMAL",
        "2026-10-30T08:00:00+08:00",
    ),
    # Whole-word "campu" and "thesi": they match only if "campus" or
    # "thesis" were (wrongly) given a plural alternative.
    (
        915,
        "Odd Words",
        "<p>The campu and thesi rows exist only to test exclusions.</p>",
        "Testing",
        "NORMAL",
        "2026-10-30T07:00:00+08:00",
    ),
    # Whole-word "form": followed by U+00B2 (category No, not a word char),
    # and preceded by U+1D400 (a letter), which blocks the second one.
    (
        913,
        "Superscript Note",
        "<p>Use form² here, not \U0001d400form.</p>",
        "Mathematics",
        "NORMAL",
        "2026-10-30T09:00:00+08:00",
    ),
    (
        912,
        "Late Item",
        "<p>Posted after now: forms.</p>",
        "Registrar",
        "NORMAL",
        "2026-11-02T10:00:01+08:00",
    ),
]


def load_excerpt_cases() -> list[tuple[str, str]]:
    spec = importlib.util.spec_from_file_location(
        "test_excerpt", ROOT / "tests" / "test_excerpt.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    marks = module.test_plain_text.pytestmark
    return [tuple(case) for case in marks[0].args[1]]


EXTRA_HTML = [
    '<p style="text-align: justify">A <strong>bold</strong> start.</p><p>Next&nbsp;para.</p>',
    "<h2>Heading</h2><ol><li>One</li><li>Two</li></ol>",
    "Tab\tand<br>\nnew line",
    "&#128512; &#x1f600; &#1114112; &#xffffffffff; &#99999999999999999999;",
    "&constructor; &toString; &__proto__; &hasOwnProperty;",
    "&NotEqualTilde; &ngE; &fjlig;",
    "<p>Unclosed <b>bold",
    "a > b and <!DOCTYPE html> c",
    "<a href=\"x\">link</a><A HREF='y'>LINK</A>",
    "  lead and trail ",
    "x<br/> y",
]


def plain_vectors() -> list[dict]:
    cases = load_excerpt_cases() + [(body, plain_text(body)) for body in EXTRA_HTML]
    out = []
    for body, expected in cases:
        if plain_text(body) != expected:
            sys.exit("test_excerpt.py disagrees with excerpt.plain_text()")
        out.append({"body": body, "expected": expected})
    return out


def cut_vectors() -> list[dict]:
    texts = [
        "a" * 499,
        "a" * 500,
        "a" * 501,
        "\U0001f600" * 501,
        "a" * 499 + "\U0001f600" + "b",
        "",
    ]
    return [{"text": t, "expected": t[:EXCERPT_CHARS]} for t in texts]


PUBLISHED_AT_TEXTS = [
    "2026-11-07T15:33:53+08:00",
    "2026-11-07T15:33:53.987+08:00",
    "2026-11-07T15:33:53.000000001+08:00",
    "2026-11-07T07:33:53Z",
    "2026-11-07T15:33:53",
    "2026-11-07T15:33:53-05:00",
    "2026-12-31T20:00:00-05:00",
    "2026-11-07T15:33+08:00",
    "2026-11-07 15:33:53+08:00",
    "2026-02-29T10:00:00+08:00",
    "2028-02-29T10:00:00+08:00",
    "2026-02-30T10:00:00+08:00",
    "2026-13-01T10:00:00+08:00",
    "2026-11-07T24:00:00+08:00",
    "2026-11-07T23:60:00+08:00",
    "2026-11-07T23:59:60+08:00",
    "2026-11-07T15:33:53+24:00",
    "2026-11-07T15:33:53+08:60",
    "2026-11-07T15:33:53+0800",
    "0999-12-31T20:00:00+08:00",
    "1000-01-01T07:00:00+00:00",
    "9999-12-31T23:59:59+08:00",
    "9999-12-31T20:00:00-05:00",
    "",
    None,
    20261107,
]


def plural_vectors() -> list[dict]:
    return [{"word": w, "expected": plural_alternative(w)} for w in PLURAL_WORDS]


def published_at_vectors() -> list[dict]:
    out = []
    for text in PUBLISHED_AT_TEXTS:
        parsed = parse_published_at(text)
        out.append(
            {
                "text": text,
                "expected": None
                if parsed is None
                else {
                    "manila": parsed[0].isoformat(timespec="seconds"),
                    "offset_added": parsed[1],
                },
            }
        )
    return out


def detail(id_, title, body, office, priority, published) -> dict:
    return {
        "id": id_,
        "title": title,
        "body": body,
        "priority": priority,
        "officeName": office,
        "publishedAt": published,
        "version": 1,
        "attachments": [],
    }


def row_vectors() -> list[dict]:
    good = detail(
        1,
        "Title",
        "<p>Body &amp; more</p>",
        "Office",
        "HIGH",
        "2026-11-07T15:33:53+08:00",
    )
    details = [
        good,
        {**good, "id": 7.0},
        {**good, "id": 7.5},
        {**good, "id": "7"},
        {**good, "id": True},
        {**good, "title": "T" * 300},
        {**good, "title": "\U0001f600" * 300},
        {**good, "title": None},
        {**good, "body": None},
        {**good, "body": "x" * 600},
        {**good, "officeName": None},
        {**good, "priority": None},
        {key: value for key, value in good.items() if key != "officeName"},
        {**good, "publishedAt": "2026-11-07T07:33:53Z"},
        {**good, "publishedAt": "2026-11-07T15:33:53"},
        {**good, "publishedAt": None},
        {**good, "publishedAt": "yesterday"},
        "not an object",
        None,
    ]
    out = []
    for value in details:
        mapped = feed_row(value)
        out.append(
            {
                "detail": value,
                "expected": None
                if mapped is None
                else {
                    "announcement": to_announcement(mapped[0]),
                    "match_title": mapped[0]["title"],
                    "match_body": mapped[0]["body"],
                    "offset_added": mapped[1],
                },
            }
        )
    return out


def search_vectors() -> dict:
    files = {
        name: json.loads(
            (ROOT / "tests" / "vectors" / f"{name}.json").read_text(encoding="utf-8")
        )
        for name in VECTOR_FILES
    }
    now_text = files["search_vectors_and_v3"]["now"]
    if any(data["now"] != now_text for data in files.values()):
        sys.exit("the search vector files no longer share one now")
    now = datetime.fromisoformat(now_text)
    details = []
    for row in files["search_vectors_and_v3"]["rows"]:
        if row["status"] != "PUBLISHED" or row["is_archived"]:
            continue  # the feed never contains these
        details.append(
            detail(
                int(row["id"].split("-")[1])
                + (100 if row["id"][0] == "s" else 200 if row["id"][0] == "p" else 0),
                row["title"],
                row["body"],
                row["office"],
                row["priority"],
                row["published_at"] + "+08:00",
            )
        )
    details += [detail(*row) for row in SYNTHETIC]
    rows = [mapped[0] for mapped in map(feed_row, details) if mapped is not None]
    queries = []
    for name, data in files.items():
        for vector in data["vectors"]:
            queries.append((f"{name}: {vector['name']}", vector["arguments"]))
    queries += [(f"flow: {q['query']}", q) for q in FLOW_QUERIES]
    queries += [(f"edge: {q['query']!r}", q) for q in EDGE_QUERIES]
    cases = []
    for label, arguments in queries:
        try:
            ids = [r["id"] for r in search_feed(rows, arguments, now, CONTRACT)]
            cases.append(
                {"name": label, "arguments": arguments, "ok": True, "expected_ids": ids}
            )
        except InvalidArguments:
            cases.append(
                {
                    "name": label,
                    "arguments": arguments,
                    "ok": False,
                    "expected_ids": None,
                }
            )
    return {"now": now_text, "details": details, "cases": cases}


def build() -> str:
    data = {
        "format": "archways feed search vectors v1",
        "generator": "scripts/export_feed_vectors.py",
        "matcher": "and_v3",
        "plain_text": plain_vectors(),
        "cut": cut_vectors(),
        "plural_alternative": plural_vectors(),
        "published_at": published_at_vectors(),
        "rows": row_vectors(),
        "search": search_vectors(),
    }
    return json.dumps(data, ensure_ascii=True, indent=1) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else None
        if current != text:
            sys.exit(f"{OUT.relative_to(ROOT)} is out of date; rerun the script")
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return
    OUT.write_bytes(text.encode("ascii"))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text):,} bytes)")


if __name__ == "__main__":
    main()
