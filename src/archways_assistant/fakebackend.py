"""Fake search_announcements backend: the rules the Spring app will apply.

The end-to-end probe runs searches through this instead of a database.
tests/vectors/search_vectors.json pins the expected ids for given rows and
arguments, so the Spring side can run the same vectors against its query.

Rules, in order:
1. Arguments are validated against the contract; invalid ones raise
   InvalidArguments, as Spring rejects them. Missing days and limit take the
   contract defaults.
2. A row is visible only if its status is PUBLISHED, it is not archived, and
   its published_at is not after now. It must also be within the last
   `days` days: now - days <= published_at <= now.
3. The query is lowercased and split on whitespace, and STOPWORDS are
   dropped. Every remaining word must appear in the title or in the body as
   a plain substring (AND across words), like ILIKE '%word%' ESCAPE '\\'
   per word. No words left means no results.
4. Newest first by published_at, ties by id ascending, then limit.
5. Each row is returned in the contract's announcement shape: published_at
   gets STORED_ZONE and becomes posted_at, and the body is cut to
   EXCERPT_CHARS characters and becomes excerpt.

Seed rows store published_at as a naive timestamp, like the database column.
Python's str.lower() stands in for Postgres case folding; they can differ
for some non-ASCII letters.

Pure: no I/O and no clock; `now` is always passed in.
"""

from datetime import datetime, timedelta, timezone

from jsonschema import Draft202012Validator

# UNVERIFIED: the zone the database stores published_at in. Confirm the
# stored zone with the team before relying on it.
STORED_ZONE = timezone(timedelta(hours=8), "Asia/Manila")
EXCERPT_CHARS = 500
PUBLISHED = "PUBLISHED"
# Small on purpose. Spring must use the same list
# (tests/vectors/search_vectors.json carries a copy).
STOPWORDS = frozenset(
    {
        # English
        "a",
        "about",
        "an",
        "and",
        "any",
        "are",
        "at",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "there",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        # Filipino
        "ang",
        "ano",
        "ba",
        "kailan",
        "mga",
        "ng",
        "po",
        "sa",
        "yung",
        # Every row is an announcement, so these words never narrow a search.
        "announcement",
        "announcements",
    }
)


class InvalidArguments(ValueError):
    pass


def ilike_pattern(word: str) -> str:
    """The ILIKE pattern Spring should bind for one query word (escape char \\)."""
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def query_words(query: str) -> list[str]:
    return [word for word in query.lower().split() if word not in STOPWORDS]


def published_at(row: dict) -> datetime:
    """The row's naive published_at with STORED_ZONE attached."""
    value = datetime.fromisoformat(row["published_at"])
    if value.tzinfo is not None:
        raise ValueError(f"{row['id']}: published_at must be naive (no zone)")
    return value.replace(tzinfo=STORED_ZONE)


def is_visible(row: dict, now: datetime) -> bool:
    """Whether the row may ever reach the model at now, ignoring the days window."""
    return (
        row["status"] == PUBLISHED
        and not row["is_archived"]
        and published_at(row) <= now
    )


def to_announcement(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "excerpt": row["body"][:EXCERPT_CHARS],
        "office": row["office"],
        "priority": row["priority"],
        "year_level": row["year_level"],
        "posted_at": published_at(row).isoformat(),
    }


def search_announcements(
    rows: list[dict], arguments: dict, now: datetime, contract: dict
) -> list[dict]:
    """Run one search over seed rows at now. See the module docstring for the rules."""
    if now.tzinfo is None:
        raise ValueError("now must have a time zone")
    schema = contract["$defs"]["arguments"]
    errors = [
        error.message for error in Draft202012Validator(schema).iter_errors(arguments)
    ]
    if errors:
        raise InvalidArguments("; ".join(sorted(errors)))
    properties = schema["properties"]
    days = arguments.get("days", properties["days"]["default"])
    limit = arguments.get("limit", properties["limit"]["default"])
    words = query_words(arguments["query"])
    if not words:
        return []

    since = now - timedelta(days=days)
    matches = []
    for row in sorted(rows, key=lambda row: row["id"]):
        if not is_visible(row, now) or published_at(row) < since:
            continue
        title, body = row["title"].lower(), row["body"].lower()
        if all(word in title or word in body for word in words):
            matches.append(row)
    # Stable sort: equal timestamps keep id order.
    matches.sort(key=published_at, reverse=True)
    return [to_announcement(row) for row in matches[:limit]]
