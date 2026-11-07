"""The on-phone feed search reference (ADR 0006) and its generated files."""

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

from archways_assistant.fakebackend import to_announcement
from archways_assistant.feedindex import feed_row, parse_published_at, search_feed

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VECTORS = ROOT / "tests" / "vectors" / "feed_vectors.json"
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text(
        encoding="utf-8"
    )
)


def load_script(name: str):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_feed_vectors_are_up_to_date():
    assert load_script("export_feed_vectors").build() == VECTORS.read_text(
        encoding="utf-8"
    )


def test_search_data_ts_is_up_to_date():
    exporter = load_script("export_search_ts")
    assert exporter.render() == exporter.OUT.read_text(encoding="utf-8")


def test_feed_vectors_are_ascii_and_lf():
    raw = VECTORS.read_bytes()
    assert raw.isascii()
    assert b"\r\n" not in raw


def detail(**changes):
    return {
        "id": 12,
        "title": "Title",
        "body": "<p>Fees &amp; dues</p>",
        "priority": "HIGH",
        "officeName": "Office",
        "publishedAt": "2026-11-07T15:33:53+08:00",
        **changes,
    }


def test_feed_row_maps_to_a_contract_row():
    row, added = feed_row(detail())
    assert not added
    assert to_announcement(row) == {
        "id": "12",
        "title": "Title",
        "excerpt": "Fees & dues",
        "office": "Office",
        "priority": "HIGH",
        "year_level": None,
        "posted_at": "2026-11-07T15:33:53+08:00",
    }


def test_year_level_is_always_null():
    """ADR 0006: the feed already filtered by the student's year level."""
    row, _ = feed_row(detail(yearLevel=2))
    assert row["year_level"] is None


def test_published_at_without_offset_assumes_manila_and_is_flagged():
    row, added = feed_row(detail(publishedAt="2026-11-07T15:33:53"))
    assert added
    assert to_announcement(row)["posted_at"] == "2026-11-07T15:33:53+08:00"


def test_published_at_is_converted_to_manila():
    instant, added = parse_published_at("2026-11-07T07:33:53Z")
    assert not added
    assert instant.isoformat() == "2026-11-07T15:33:53+08:00"


def test_items_without_a_usable_published_at_are_skipped():
    for value in (None, "", "yesterday", "2026-11-07T15:33+08:00", 20261107):
        assert feed_row(detail(publishedAt=value)) is None, value


def test_search_matches_plain_text_not_html():
    """Matching uses the plain text: a tag name is not a word of the body."""
    rows = [feed_row(detail(body="<strong>Exam</strong> schedule"))[0]]
    now = datetime.fromisoformat("2026-11-07T16:00:00+08:00")
    assert search_feed(rows, {"query": "strong"}, now, CONTRACT) == []
    assert [r["id"] for r in search_feed(rows, {"query": "exams"}, now, CONTRACT)] == [
        "12"
    ]
