"""The snapshot loader, on tiny fake snapshots (no real announcements)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant.fakebackend import STORED_ZONE, is_visible, to_announcement
from archways_assistant.snapshot import SEED_KEYS, SnapshotError, load_snapshot

ROOT = Path(__file__).resolve().parents[1]
SECRET = "Fake body text that must never appear in an error"
FAKE = [
    {
        "id": "101",
        "title": "Fake title one",
        "body": SECRET + " ñ, with a <b>tag</b> and a \\ backslash\nand a line break.",
        "office": "Fake Office",
        "priority": "URGENT",
        "year_level": None,
        "published_at": "2026-11-02T08:30:00",
    },
    {
        "published_at": "2026-10-30T17:05:09",
        "year_level": 3,
        "priority": "STANDARD",
        "office": "Another Fake Office",
        "body": "Short.",
        "title": "Fake title two",
        "id": "102",
    },
]


def write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_bytes(data)
    return path


def dump(rows) -> bytes:
    return json.dumps(rows, ensure_ascii=False).encode("utf-8")


def rejected(tmp_path: Path, data: bytes) -> str:
    with pytest.raises(SnapshotError) as caught:
        load_snapshot(write(tmp_path, data))
    message = str(caught.value)
    assert SECRET not in message and "Fake title" not in message
    return message


def changed(index: int, **fields) -> bytes:
    rows = json.loads(json.dumps(FAKE))
    for key, value in fields.items():
        if value is KeyError:
            del rows[index][key]
        else:
            rows[index][key] = value
    return dump(rows)


PLAIN_0 = SECRET + " ñ, with a tag and a \\ backslash and a line break."


def test_maps_to_seed_rows(tmp_path):
    snapshot = load_snapshot(write(tmp_path, dump(FAKE)))
    rows = snapshot.rows
    assert rows == [
        {
            **FAKE[0],
            "body": PLAIN_0,
            "status": "PUBLISHED",
            "is_archived": False,
            "scheduled": False,
        },
        {**FAKE[1], "status": "PUBLISHED", "is_archived": False, "scheduled": False},
    ]
    assert all(tuple(row) == SEED_KEYS for row in rows)
    assert snapshot.tagged_ids == ["101"]
    assert snapshot.reference_ids == []


def test_reports_references(tmp_path):
    snapshot = load_snapshot(write(tmp_path, changed(1, body="A&nbsp;B &amp; C")))
    assert snapshot.tagged_ids == ["101"]
    assert snapshot.reference_ids == ["102"]
    assert snapshot.rows[1]["body"] == "A B & C"


def test_seed_keys_match_the_seed_file():
    seed = json.loads(
        (ROOT / "data" / "seed" / "announcements.json").read_text("utf-8")
    )
    assert all(tuple(row) == SEED_KEYS for row in seed)


def test_rows_work_with_fakebackend(tmp_path):
    rows = load_snapshot(write(tmp_path, dump(FAKE))).rows
    now = datetime(2026, 11, 6, 12, tzinfo=STORED_ZONE)
    assert all(is_visible(row, now) for row in rows)
    result = to_announcement(rows[0])
    assert result["posted_at"] == "2026-11-02T08:30:00+08:00"
    assert result["excerpt"] == PLAIN_0


def test_empty_array(tmp_path):
    snapshot = load_snapshot(write(tmp_path, b"[]\n"))
    assert (snapshot.rows, snapshot.tagged_ids, snapshot.reference_ids) == ([], [], [])


def test_rejects_non_utf8(tmp_path):
    data = dump(FAKE).decode("utf-8").encode("cp1252")
    assert "ENCODING 'UTF8'" in rejected(tmp_path, data)


def test_rejects_bom(tmp_path):
    assert "BOM" in rejected(tmp_path, b"\xef\xbb\xbf" + dump(FAKE))


def test_names_copy_text_format(tmp_path):
    # What COPY's text format makes of json_agg output.
    copied = dump(FAKE).replace(b"}, {", b"}, \\n {").replace(b"\\\\", b"\\\\\\\\")
    assert "COPY's text format" in rejected(tmp_path, copied)


def test_rejects_invalid_json_without_hint(tmp_path):
    message = rejected(tmp_path, b"[{")
    assert "not valid JSON" in message and "COPY" not in message


@pytest.mark.parametrize(
    "data",
    [b"{}", b'"x"', b"null", b"[1]", b"[[]]"],
)
def test_rejects_wrong_structure(tmp_path, data):
    rejected(tmp_path, data)


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"office": KeyError}, "keys differ"),
        ({"office_id": 3}, "keys differ"),
        ({"id": 101}, "id is not a string"),
        ({"id": ""}, "id is empty"),
        ({"title": ""}, "title is empty"),
        ({"office": ""}, "office is empty"),
        ({"body": None}, "body is not a string"),
        ({"priority": 1}, "priority is not a string"),
        ({"year_level": True}, "year_level"),
        ({"year_level": 1.5}, "year_level"),
        ({"year_level": "1"}, "year_level"),
        ({"published_at": None}, "published_at is not a string"),
        ({"published_at": "2026-11-02T08:30:00+08:00"}, "published_at"),
        ({"published_at": "2026-11-02T08:30:00.123456"}, "published_at"),
        ({"published_at": "2026-11-02"}, "published_at"),
        ({"published_at": "2026-13-02T08:30:00"}, "published_at"),
    ],
)
def test_rejects_bad_fields(tmp_path, fields, expected):
    message = rejected(tmp_path, changed(0, **fields))
    assert expected in message
    assert "element 0" in message


def test_rejects_duplicate_ids(tmp_path):
    assert "duplicate ids: ['101']" in rejected(tmp_path, changed(1, id="101"))


def test_rejects_duplicate_json_keys(tmp_path):
    data = dump(FAKE).replace(b'"id": "102"', b'"id": "102", "id": "103"')
    assert "duplicate key" in rejected(tmp_path, data)


def test_data_local_is_gitignored():
    lines = (ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert "data/local/" in lines
