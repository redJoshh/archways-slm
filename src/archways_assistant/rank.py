"""rank_v1: rank matched rows by overlap with the raw question, before the cut.

The rule is docs/plans/accuracy-phase.md, "rank_v1 rule, pre-registered"
(2026-11-14), checked by the hand-written tests/vectors/rank_vectors.json.
assistant-ts ports it (src/rank.ts).

- Question anchors: claims(question lowercased): its dates, and its numbers
  (a date's year is a number, its day is not).
- Question content words: the lowercased question with parsed dates blanked,
  split into runs of and_v3 word characters; tokens with a digit, tokens of
  one code point, AND_V2_STOPWORDS and rank_stopwords_v1 dropped; first
  occurrence kept, in order.
- Per row (lowercased title and whole plain-text body): a word is found by
  the matcher's test for a one-word query; a date anchor is found in
  claims(title + "\\n" + body).dates; a number anchor in
  merged_claims([title + "\\n" + body]).numbers.
- points = words found + 3 x anchors found; possible = words + 3 x anchors.
"""

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from archways_assistant.e2escore import Claims, claims, claims_and_rest, merged_claims
from archways_assistant.fakebackend import (
    AND_V2_STOPWORDS,
    SYNONYMS,
    is_word_char,
    plural_alternative,
    whole_word_in,
)

RANKS = ("rank_v1",)
ANCHOR_WEIGHT = 3
_STOPWORDS_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "rank_stopwords_v1.json"
)
_STOPWORDS_FILE = json.loads(_STOPWORDS_PATH.read_text(encoding="utf-8"))
RANK_STOPWORDS = frozenset(_STOPWORDS_FILE["filipino"] + _STOPWORDS_FILE["domain"])


@dataclass(frozen=True)
class Terms:
    words: tuple[str, ...]
    dates: frozenset[tuple[int, int]]
    numbers: frozenset[int]

    @property
    def possible(self) -> int:
        return len(self.words) + ANCHOR_WEIGHT * (len(self.dates) + len(self.numbers))


def tokens(text: str) -> list[str]:
    """Maximal runs of and_v3 word characters, in order."""
    out, current = [], []
    for ch in text:
        if is_word_char(ch):
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def question_terms(question: str) -> Terms:
    found, rest = claims_and_rest(question.lower())
    words: list[str] = []
    for token in tokens(rest):
        if (
            len(token) < 2
            or any(unicodedata.category(ch) == "Nd" for ch in token)
            or token in AND_V2_STOPWORDS
            or token in RANK_STOPWORDS
            or token in words
        ):
            continue
        words.append(token)
    return Terms(tuple(words), found.dates, found.numbers)


def word_found(
    word: str, title: str, body: str, synonyms: dict[str, list[str]] = SYNONYMS
) -> bool:
    """The matcher's one-word test (and_v3 rules; synonyms of the matcher in use)."""
    if any(alt in title or alt in body for alt in [word, *synonyms.get(word, [])]):
        return True
    stem = plural_alternative(word)
    return stem is not None and (
        whole_word_in(stem, title) or whole_word_in(stem, body)
    )


def row_claims(title: str, body: str) -> tuple[Claims, Claims]:
    """(claims, merged_claims) of a row's lowercased title and body."""
    text = f"{title}\n{body}"
    return claims(text), merged_claims([text])


def points(
    terms: Terms, title: str, body: str, synonyms: dict[str, list[str]] = SYNONYMS
) -> int:
    own, merged = row_claims(title, body)
    words = sum(word_found(word, title, body, synonyms) for word in terms.words)
    anchors = len(terms.dates & own.dates) + len(terms.numbers & merged.numbers)
    return words + ANCHOR_WEIGHT * anchors


GATES = ("gate_v1",)
GATE_THETAS = ((0, 1), (1, 4), (1, 3), (1, 2), (2, 3), (3, 4))  # fixed grid


def gate_v1(
    question: str,
    title: str,
    body: str,
    synonyms: dict[str, list[str]],
    p: int,
    q: int,
) -> bool:
    """gate_v1 (accuracy-phase.md (d)): is the top result about the question?

    title and body are the top result's lowercased title and whole body;
    synonyms are the matcher's. Passes if points x q >= p x possible for
    theta = p/q (integers only); possible 0 always passes.
    """
    if q <= 0 or p < 0:
        raise ValueError("theta must be p/q with p >= 0 and q > 0")
    terms = question_terms(question)
    if terms.possible == 0:
        return True
    return points(terms, title, body, synonyms) * q >= p * terms.possible
