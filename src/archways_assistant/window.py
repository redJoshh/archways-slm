"""excerpt_v2_centred: a 500-code-point excerpt around the matched words.

The rule is docs/plans/accuracy-phase.md, "excerpt_v2_centred rule,
pre-registered" (2026-11-14), checked by the hand-derived
tests/vectors/window_vectors.json. assistant-ts ports it (src/window.ts).

1. If lowercasing the body changes its length, the first 500 (positions in
   the lowercased text would not map back).
2. Anchor, in the lowercased body: (a) the earliest date span claims()
   parses whose (month, day) is a question date; else (b) the earliest match
   of a rank_v1 content word (substring, its synonyms under the matcher, or
   its plural alternative as a whole word); else (c) the same over the
   matcher's groups for the model's query; ties go to the shorter match.
3. No anchor, or the anchor ends at or before 500: the first 500.
4. start = max(0, min(anchor_start - 250, length - 500)); if the code point
   before start is not a space, move to just after the first space in
   [start, start + 30) if any; the excerpt is the ellipsis plus 499 code
   points from start.
"""

from archways_assistant.e2escore import date_scan
from archways_assistant.fakebackend import (
    AND_V3_RULES,
    EXCERPT_CHARS,
    is_word_char,
    plural_alternative,
    plural_groups,
)
from archways_assistant.rank import question_terms

EXCERPTS = ("excerpt_v2_centred",)
ELLIPSIS = "…"
LEAD = 250
SNAP = 30


def first_whole_word(stem: str, text: str) -> int:
    """The first index of stem as a whole word in text, or -1."""
    start = text.find(stem)
    while start != -1:
        end = start + len(stem)
        before = start == 0 or not is_word_char(text[start - 1])
        after = end == len(text) or not is_word_char(text[end])
        if before and after:
            return start
        start = text.find(stem, start + 1)
    return -1


def earliest(groups: list[tuple[list[str], list[str]]], text: str):
    """The earliest (start, end) of any substring alt or whole-word stem."""
    best = None
    for subs, stems in groups:
        for alt in subs:
            i = text.find(alt)
            if i != -1 and (best is None or (i, i + len(alt)) < best):
                best = (i, i + len(alt))
        for stem in stems:
            i = first_whole_word(stem, text)
            if i != -1 and (best is None or (i, i + len(stem)) < best):
                best = (i, i + len(stem))
    return best


def anchor(body: str, question: str, query: str, matcher: str):
    """The window's anchor (start, end) in body, or None."""
    lowered = body.lower()
    terms = question_terms(question)
    if terms.dates:
        _, _, spans = date_scan(lowered)
        found = [(s, e) for s, e, date in spans if date in terms.dates]
        if found:
            return min(found)
    synonyms = AND_V3_RULES[matcher]
    words = [
        (
            [w, *synonyms.get(w, [])],
            [] if (stem := plural_alternative(w)) is None else [stem],
        )
        for w in terms.words
    ]
    return earliest(words, lowered) or earliest(plural_groups(query, synonyms), lowered)


def centred_excerpt(body: str, question: str, query: str, matcher: str) -> str:
    if len(body.lower()) != len(body):
        return body[:EXCERPT_CHARS]
    found = anchor(body, question, query, matcher)
    if found is None or found[1] <= EXCERPT_CHARS:
        return body[:EXCERPT_CHARS]
    start = max(0, min(found[0] - LEAD, len(body) - EXCERPT_CHARS))
    if start > 0 and body[start - 1] != " ":
        space = body.find(" ", start, start + SNAP)
        if space != -1:
            start = space + 1
    if start == 0:
        return body[:EXCERPT_CHARS]
    return ELLIPSIS + body[start : start + EXCERPT_CHARS - 1]
