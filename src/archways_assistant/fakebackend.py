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
3. Matching depends on the matcher (default DEFAULT_MATCHER):
   - and_v1: the query is lowercased and split on whitespace, and STOPWORDS
     are dropped. Every remaining word must appear in the title or in the
     body as a plain substring (AND across words), like
     ILIKE '%word%' ESCAPE '\\' per word.
   - and_v2 (search contract v2): and_v1 plus the frozen map in
     contracts/search_synonyms_v1.json. The map's extra_stopwords
     ("kapag") are dropped too (AND_V2_STOPWORDS; and_v1 and prefix_v2
     keep STOPWORDS). Each remaining word becomes a group: the word, then
     its synonyms (SYNONYMS; keys are whole lowercased query words). A
     group matches if any member is a plain substring of the title or body
     (OR within a group); every group must match (AND across groups).
     The map was built from dev-set retrieval failures and is never tuned
     afterwards: a change is a new map file and a new matcher. Spring must
     load the same file and pass tests/vectors/search_vectors_and_v2.json.
     Untested on real announcements: "due" also matches "due to".
   - prefix_v2: query, title and body are lowercased and split into words
     (runs of letters and digits; anything else separates words), and
     STOPWORDS are dropped from the query. Each query word of 5 or more
     characters becomes its first 4 characters (its stem); shorter words
     stay whole. A row matches if at least ceil(n/2) of the n stems each
     start some word of the title or body. A stem that starts a title word
     scores 2, otherwise one that starts a body word scores 1.
   No query words left means no results.
4. Highest score first (and_v1 and and_v2 score every match 0), then newest
   published_at, then id ascending; then limit.
5. Each row is returned in the contract's announcement shape: published_at
   gets STORED_ZONE and becomes posted_at, and the body is cut to
   EXCERPT_CHARS characters and becomes excerpt.

Seed rows store published_at as a naive timestamp, like the database column.
Python's str.lower() stands in for Postgres case folding; they can differ
for some non-ASCII letters.

Pure apart from reading the frozen synonym map once at import: no other
I/O and no clock; `now` is always passed in.
"""

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


SYNONYMS_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "search_synonyms_v1.json"
)
_SYNONYM_MAP = json.loads(SYNONYMS_PATH.read_text(encoding="utf-8"))
SYNONYMS: dict[str, list[str]] = _SYNONYM_MAP["synonyms"]
AND_V2_STOPWORDS = STOPWORDS | frozenset(_SYNONYM_MAP["extra_stopwords"])
MATCHERS = ("and_v1", "prefix_v2", "and_v2")
DEFAULT_MATCHER = "and_v1"
# prefix_v2: words this long or longer are cut to their first STEM_CHARS.
STEM_MIN_CHARS = 5
STEM_CHARS = 4
WORD = re.compile(r"[^\W_]+")


class InvalidArguments(ValueError):
    pass


def ilike_pattern(word: str) -> str:
    """The ILIKE pattern Spring should bind for one query word (escape char \\)."""
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def query_words(query: str) -> list[str]:
    return [word for word in query.lower().split() if word not in STOPWORDS]


def synonym_groups(query: str) -> list[list[str]]:
    """and_v2 groups, in query order: each word, then its synonyms."""
    words = [word for word in query.lower().split() if word not in AND_V2_STOPWORDS]
    return [[word, *SYNONYMS.get(word, [])] for word in words]


def prefix_stems(query: str) -> list[str]:
    """prefix_v2 query stems, in query order."""
    words = [word for word in WORD.findall(query.lower()) if word not in STOPWORDS]
    return [
        word[:STEM_CHARS] if len(word) >= STEM_MIN_CHARS else word for word in words
    ]


def prefix_score(stems: list[str], title: str, body: str) -> int | None:
    """prefix_v2 score of a row, or None if too few stems match."""
    title_words = WORD.findall(title.lower())
    body_words = WORD.findall(body.lower())
    matched = score = 0
    for stem in stems:
        if any(word.startswith(stem) for word in title_words):
            matched += 1
            score += 2
        elif any(word.startswith(stem) for word in body_words):
            matched += 1
            score += 1
    return score if matched >= math.ceil(len(stems) / 2) else None


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
    rows: list[dict],
    arguments: dict,
    now: datetime,
    contract: dict,
    matcher: str = DEFAULT_MATCHER,
) -> list[dict]:
    """Run one search over seed rows at now. See the module docstring for the rules."""
    if now.tzinfo is None:
        raise ValueError("now must have a time zone")
    if matcher not in MATCHERS:
        raise ValueError(f"unknown matcher {matcher!r}")
    schema = contract["$defs"]["arguments"]
    errors = [
        error.message for error in Draft202012Validator(schema).iter_errors(arguments)
    ]
    if errors:
        raise InvalidArguments("; ".join(sorted(errors)))
    properties = schema["properties"]
    days = arguments.get("days", properties["days"]["default"])
    limit = arguments.get("limit", properties["limit"]["default"])
    if matcher == "and_v1":
        words = query_words(arguments["query"])
    elif matcher == "and_v2":
        words = synonym_groups(arguments["query"])
    else:
        words = prefix_stems(arguments["query"])
    if not words:
        return []

    since = now - timedelta(days=days)
    matches = []  # (score, row)
    for row in rows:
        if not is_visible(row, now) or published_at(row) < since:
            continue
        if matcher == "and_v1":
            title, body = row["title"].lower(), row["body"].lower()
            if all(word in title or word in body for word in words):
                matches.append((0, row))
        elif matcher == "and_v2":
            title, body = row["title"].lower(), row["body"].lower()
            if all(
                any(alt in title or alt in body for alt in group) for group in words
            ):
                matches.append((0, row))
        else:
            score = prefix_score(words, row["title"], row["body"])
            if score is not None:
                matches.append((score, row))
    matches.sort(
        key=lambda match: (
            -match[0],
            -published_at(match[1]).timestamp(),
            match[1]["id"],
        )
    )
    return [to_announcement(row) for _, row in matches[:limit]]
