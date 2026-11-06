"""Load a local announcements snapshot as seed-shaped rows.

The snapshot is a JSON array exported by hand from a Spring database with
scripts/snapshot_export.psql and kept in
data/local/ (gitignored). This module only reads that file: no network, no
database.

Each element must be an object with exactly these keys:
- id: a non-empty string (the export writes announcement_id as text)
- title, body, office, priority: strings; title and office not empty
- year_level: an integer or null (not a boolean)
- published_at: a naive local timestamp "YYYY-MM-DDTHH:MM:SS", as stored
  in the TIMESTAMP column
Ids must be unique. Duplicate keys inside an object are rejected.

The file must be UTF-8 without a BOM and valid JSON as a whole. Two
export mistakes are named in the error: a non-UTF-8 client encoding, and
COPY's text format, which writes json_agg's line breaks as a literal
backslash-n and doubles backslashes.

Rows come back in the shape of data/seed/announcements.json, so fakebackend
can serve them. Each body is replaced by excerpt.plain_text(body), the
contract v2 excerpt rule (tags stripped, references decoded, whitespace
collapsed); fakebackend.to_announcement then cuts it to the excerpt length.
Snapshot.tagged_ids and Snapshot.reference_ids name the bodies that had tags
or character references before that. The export already applied the visibility allowlist
(PUBLISHED, not archived, a student-visible academic year, published), so
status, is_archived and scheduled only restate it.

Error messages name the element index, id and key, never announcement text.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from archways_assistant.excerpt import has_references, has_tags, plain_text
from archways_assistant.fakebackend import PUBLISHED

SNAPSHOT_KEYS = (
    "id",
    "title",
    "body",
    "office",
    "priority",
    "year_level",
    "published_at",
)
SEED_KEYS = (
    "id",
    "title",
    "body",
    "office",
    "priority",
    "year_level",
    "published_at",
    "status",
    "is_archived",
    "scheduled",
)
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\Z")
# json_agg separates elements with ",\n " and COPY's text format writes the
# line break as a backslash and "n" outside any JSON string.
COPY_TEXT_ARTIFACT = re.compile(r"\}, \\n \{")


class SnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class Snapshot:
    rows: list[dict]
    tagged_ids: list[str]
    reference_ids: list[str]


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise SnapshotError("an object has a duplicate key")
    return dict(pairs)


def decode(data: bytes) -> list:
    if data.startswith(b"\xef\xbb\xbf"):
        raise SnapshotError("the file starts with a UTF-8 BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SnapshotError(
            f"not UTF-8 (byte {error.start}); export with ENCODING 'UTF8'"
        ) from None
    try:
        value = json.loads(text, object_pairs_hook=no_duplicate_keys)
    except json.JSONDecodeError as error:
        hint = (
            "; it looks like COPY's text format (use scripts/snapshot_export.psql)"
            if COPY_TEXT_ARTIFACT.search(text)
            else ""
        )
        raise SnapshotError(f"not valid JSON at character {error.pos}{hint}") from None
    if not isinstance(value, list):
        raise SnapshotError("the snapshot is not a JSON array")
    return value


def to_seed_row(index: int, item: object) -> dict:
    if not isinstance(item, dict):
        raise SnapshotError(f"element {index} is not an object")
    where = f"element {index}"
    if isinstance(item.get("id"), str):
        where += f" (id {item['id']})"
    if set(item) != set(SNAPSHOT_KEYS):
        missing = sorted(set(SNAPSHOT_KEYS) - set(item))
        extra = sorted(set(item) - set(SNAPSHOT_KEYS))
        raise SnapshotError(f"{where}: keys differ (missing {missing}, extra {extra})")
    for key in ("id", "title", "body", "office", "priority", "published_at"):
        if not isinstance(item[key], str):
            raise SnapshotError(f"{where}: {key} is not a string")
    for key in ("id", "title", "office"):
        if not item[key]:
            raise SnapshotError(f"{where}: {key} is empty")
    year = item["year_level"]
    if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
        raise SnapshotError(f"{where}: year_level is not an integer or null")
    try:
        if not TIMESTAMP.match(item["published_at"]):
            raise ValueError
        datetime.fromisoformat(item["published_at"])
    except ValueError:
        raise SnapshotError(
            f"{where}: published_at is not YYYY-MM-DDTHH:MM:SS"
        ) from None
    return {
        "id": item["id"],
        "title": item["title"],
        "body": plain_text(item["body"]),
        "office": item["office"],
        "priority": item["priority"],
        "year_level": year,
        "published_at": item["published_at"],
        "status": PUBLISHED,
        "is_archived": False,
        "scheduled": False,
    }


def load_snapshot(path: Path) -> Snapshot:
    items = decode(path.read_bytes())
    rows = [to_seed_row(i, item) for i, item in enumerate(items)]
    ids = [row["id"] for row in rows]
    duplicates = sorted({row_id for row_id in ids if ids.count(row_id) > 1})
    if duplicates:
        raise SnapshotError(f"duplicate ids: {duplicates}")
    return Snapshot(
        rows=rows,
        tagged_ids=[item["id"] for item in items if has_tags(item["body"])],
        reference_ids=[item["id"] for item in items if has_references(item["body"])],
    )
