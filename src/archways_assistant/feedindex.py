"""On-phone search over the student's feed (ADR 0006): the reference.

assistant-ts ports this (src/feed.ts, src/search.ts); the parity vectors in
tests/vectors/feed_vectors.json come from here.

The phone indexes every item of the student's feed: GET /announcements
(Slice pages) for the ids, then GET /announcements/{id} for each detail
(never the read POST). This module covers what happens to one detail and
how the index is searched; fetching, timing and refreshing are I/O and
live only in TypeScript.

feed_row(detail) makes a seed-shaped row, so fakebackend's and_v3 search
runs on it unchanged:
- id: the integral JSON number as decimal digits (7.0 and 7 give "7")
- title: the detail title, cut to 255 code points (the contract maximum)
- body: excerpt.plain_text(detail body) (contract v2 rule: tags stripped,
  references decoded, whitespace collapsed). Matching uses the whole plain
  text; fakebackend.to_announcement cuts the excerpt to 500.
- office: officeName (a missing or null one becomes "")
- priority: priority (missing or null becomes "")
- year_level: None for every item: the feed already filtered by the
  student's year level (ADR 0006), so the model can't say "for 2nd-year
  students" unless the text says so.
- published_at: publishedAt converted to Manila (+08:00), truncated to
  whole seconds, as a naive timestamp (fakebackend attaches +08:00 again,
  so posted_at is "YYYY-MM-DDTHH:MM:SS+08:00").
- status PUBLISHED, is_archived False, scheduled False: the feed already
  applied visibility (including FOR_DELETION posts, which the client can't
  tell apart; ADR 0006).

publishedAt must match PUBLISHED_AT: an ISO 8601 date and time with
seconds, optional fraction, and an offset "Z" or "+HH:MM"/"-HH:MM". The API
sends OffsetDateTime with Asia/Manila attached (AnnouncementFeedMapper,
unverified against a live response). Without an offset, +08:00 is assumed
and the row is flagged offset_added: that assumes the server clock is
Manila time, the still-open time-zone check. Anything else (null, a
non-string, no seconds, an impossible date or time, an offset over
23:59, a Manila year outside 1000-9999) skips the item.

search_feed(rows, arguments, now): fakebackend.search_announcements with
matcher and_v3 over feed rows: contract validation and defaults (days 7,
limit 5), the days window on published_at, newest first then id; pinned is
ignored.
"""

import re
from datetime import datetime, timedelta, timezone

from archways_assistant.assistant import is_integral
from archways_assistant.excerpt import plain_text
from archways_assistant.fakebackend import (
    PUBLISHED,
    is_visible,
    published_at,
    search_announcements,
    to_announcement,
)

MANILA = timezone(timedelta(hours=8))
TITLE_MAX_CHARS = 255
# The Manila instant's year must be in this range, or the item is skipped.
YEAR_MIN = 1000
YEAR_MAX = 9999
PUBLISHED_AT = re.compile(
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})(?P<fraction>\.[0-9]+)?"
    r"(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})?\Z"
)


def parse_published_at(value) -> tuple[datetime, bool] | None:
    """(the instant in Manila, truncated to seconds; offset_added), or None."""
    if not isinstance(value, str):
        return None
    match = PUBLISHED_AT.match(value)
    if match is None:
        return None
    offset = match["offset"]
    added = offset is None
    text = f"{match['date']}T{match['time']}" + (
        "+08:00" if added else ("+00:00" if offset == "Z" else offset)
    )
    try:
        instant = datetime.fromisoformat(text)
    except ValueError:
        return None
    hours, minutes = int(text[-5:-3]), int(text[-2:])
    if hours > 23 or minutes > 59:
        return None
    try:
        manila = instant.astimezone(MANILA)
    except OverflowError:
        return None
    if not YEAR_MIN <= manila.year <= YEAR_MAX:
        return None
    return manila, added


def text_field(value) -> str:
    return value if isinstance(value, str) else ""


def feed_row(detail) -> tuple[dict, bool] | None:
    """(seed-shaped row, offset_added) for one feed detail, or None to skip."""
    if not isinstance(detail, dict):
        return None
    if not is_integral(detail.get("id")):
        return None
    if not isinstance(detail.get("title"), str) or not isinstance(
        detail.get("body"), str
    ):
        return None
    parsed = parse_published_at(detail.get("publishedAt"))
    if parsed is None:
        return None
    instant, added = parsed
    row = {
        "id": str(int(detail["id"])),
        "title": detail["title"][:TITLE_MAX_CHARS],
        "body": plain_text(detail["body"]),
        "office": text_field(detail.get("officeName")),
        "priority": text_field(detail.get("priority")),
        "year_level": None,
        "published_at": instant.replace(tzinfo=None).isoformat(timespec="seconds"),
        "status": PUBLISHED,
        "is_archived": False,
        "scheduled": False,
    }
    return row, added


def search_feed(
    rows: list[dict],
    arguments: dict,
    now: datetime,
    contract: dict,
    *,
    question: str | None = None,
    rank: str | None = None,
    matcher: str = "and_v3",
    excerpt: str | None = None,
) -> list[dict]:
    """and_v3 (or and_v4) over feed rows; rank "rank_v1" orders by the question."""
    if matcher not in ("and_v3", "and_v4"):
        raise ValueError(f"the feed search runs and_v3 or and_v4, not {matcher!r}")
    return search_announcements(
        rows,
        arguments,
        now,
        contract,
        matcher=matcher,
        question=question,
        rank=rank,
        excerpt=excerpt,
    )


RETRIES = ("retry_v1",)


def search_feed_retry(
    rows: list[dict],
    arguments: dict,
    now: datetime,
    contract: dict,
    *,
    question: str,
    rank: str = "rank_v1",
    retry: str | None = "retry_v1",
) -> tuple[list[dict], bool]:
    """search_feed, then retry_v1 if it found nothing: (results, retried).

    retry_v1 (accuracy-phase.md, pre-registered 2026-11-14): only after a
    valid search with 0 results; the question's rank_v1 content words, a row
    matching if any one is found by the matcher's one-word test; the model's
    days and limit kept; ordered by rank_v1, then newest, then id; cut after.
    No content words: no retry. Invalid arguments raise, as search_feed does.
    """
    from archways_assistant import rank as ranking

    if retry is not None and retry not in RETRIES:
        raise ValueError(f"unknown retry {retry!r}")
    results = search_feed(rows, arguments, now, contract, question=question, rank=rank)
    if results or retry is None:
        return results, False
    terms = ranking.question_terms(question)
    if not terms.words:
        return [], False
    properties = contract["$defs"]["arguments"]["properties"]
    days = arguments.get("days", properties["days"]["default"])
    limit = arguments.get("limit", properties["limit"]["default"])
    since = now - timedelta(days=days)
    found = []
    for row in rows:
        if not is_visible(row, now) or published_at(row) < since:
            continue
        title, body = row["title"].lower(), row["body"].lower()
        if any(ranking.word_found(word, title, body) for word in terms.words):
            found.append((ranking.points(terms, title, body), row))
    found.sort(
        key=lambda match: (
            -match[0],
            -published_at(match[1]).timestamp(),
            match[1]["id"],
        )
    )
    return [to_announcement(row) for _, row in found[:limit]], True
