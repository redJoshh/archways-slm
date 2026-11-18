"""past_date_v1 (v2 fix (c)): " (already passed)" after past dates in the AI answer.

The rule is docs/plans/v2-improvements.md, "past_date_v1 rule,
pre-registered" (2026-11-18), checked by the hand-written
tests/vectors/past_date_vectors.json. assistant-ts ports it
(src/pastDate.ts).

- Spans: exactly e2escore.date_scan's (the guard's and the scorer's parse),
  sorted by start. A span's year: YYYY-MM-DD's first four digits, else a
  four-digit run that ends the span, else none.
- A year-less date takes the single year that the cited sources (each
  title + "\\n" + excerpt) give for the same (month, day); none or several:
  left.
- Two consecutive spans joined only by to/until/through/thru or a dash
  (whitespace and the guard's spaces stripped, lowercased) are a range:
  judged by the end, the note after the end.
- Past: strictly before now's Manila date. Impossible dates are left.
- Only the AI-answer text (and (d)'s quotes); never the results list.
"""

import re
from datetime import date, datetime, timedelta, timezone

from archways_assistant.e2escore import SPACE_TABLE, date_scan

PAST_DATE_V1 = "past_date_v1"
CODE = "past_date"
NOTE = " (already passed)"
RANGE_JOINERS = ("to", "until", "through", "thru", "-", "–", "—")
ASCII_WHITESPACE = " \t\n\r\f\v"
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TRAILING_DIGITS = re.compile(r"[0-9]+$")
MANILA = timezone(timedelta(hours=8))


def spans_with_years(text: str) -> list[tuple[int, int, tuple[int, int], int | None]]:
    """date_scan's spans of text, sorted, each with its year (or None)."""
    _, _, spans = date_scan(text)
    out = []
    for start, end, month_day in sorted(spans):
        segment = text[start:end]
        year = None
        if ISO_DATE.fullmatch(segment):
            year = int(segment[:4])
        else:
            digits = TRAILING_DIGITS.search(segment)
            if digits and len(digits.group()) == 4:
                year = int(digits.group())
        out.append((start, end, month_day, year))
    return out


def resolve_year(month_day: tuple[int, int], sources: list[str]) -> int | None:
    years = {
        year
        for source in sources
        for _, _, found, year in spans_with_years(source)
        if found == month_day and year is not None
    }
    return years.pop() if len(years) == 1 else None


def is_past(year: int, month_day: tuple[int, int], today: date) -> bool:
    try:
        day = date(year, *month_day)
    except ValueError:
        return False
    return day < today


def annotate(text: str, sources: list[str], now: datetime) -> str:
    """text with NOTE after each past date (or past range end)."""
    if now.tzinfo is None:
        raise ValueError("now must have a time zone")
    today = now.astimezone(MANILA).date()
    spans = spans_with_years(text)
    spaced = text.translate(SPACE_TABLE)
    inserts = []
    index = 0
    while index < len(spans):
        _, end, month_day, year = spans[index]
        if index + 1 < len(spans):
            next_start, next_end, next_day, next_year = spans[index + 1]
            joiner = spaced[end:next_start].strip(ASCII_WHITESPACE).lower()
            if joiner in RANGE_JOINERS:
                end, month_day, year = next_end, next_day, next_year
                index += 1
        index += 1
        if year is None:
            year = resolve_year(month_day, sources)
        if year is not None and is_past(year, month_day, today):
            inserts.append(end)
    for at in sorted(inserts, reverse=True):
        text = text[:at] + NOTE + text[at:]
    return text


def result_sources(results: list[dict]) -> list[str]:
    """The cited sources of an AI answer: every listed result."""
    return [f"{r['title']}\n{r['excerpt']}" for r in results]
