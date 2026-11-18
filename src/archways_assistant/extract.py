"""extract_v1 (v2 fix (d)): when/what-time questions answered by quoting the source.

The rule is docs/plans/v2-improvements.md, "extract_v1 rule, pre-registered"
(2026-11-18), checked by the hand-written tests/vectors/extract_vectors.json.
assistant-ts ports it (src/extract.ts).

1. Classified: a time phrase and no entity phrase in the question's tokens
   (consecutive whole tokens).
2. Reduced terms: rank_v1's question terms without the matched time
   phrases' tokens (dates and numbers kept).
3. Admissible: at least one reduced word, and results[0]'s title + excerpt
   score every reduced word and anchor (rank_v1 points, always the v3 map).
4. Sentences: the title, then the excerpt split at newlines and after
   . ! ? + whitespace + an uppercase letter or digit (not after a listed
   abbreviation); a 500-code-point excerpt drops its last sentence.
5.-7. The candidate (date or time) with the most points, earlier on ties,
   cut to 300 code points outside date and time spans.
8. The guard must pass the quote. (c)'s note is added by the flow.
"""

import re
from dataclasses import dataclass

from archways_assistant.e2escore import SPACE_TABLE, date_scan, guard
from archways_assistant.fakebackend import EXCERPT_CHARS, SYNONYMS_V3
from archways_assistant.rank import Terms, points, question_terms, tokens

EXTRACT_V1 = "extract_v1"
LABEL = "From the announcement below:"
LABEL_SEPARATOR = "\n"
TIME_PHRASES = tuple(
    tuple(p.split())
    for p in (
        "when",
        "what time",
        "what date",
        "what day",
        "until when",
        "until what time",
        "how long",
        "kailan",
        "hanggang kailan",
        "anong oras",
        "anong araw",
        "anong petsa",
        "ilang araw",
    )
)
ENTITY_PHRASES = tuple(
    tuple(p.split()) for p in ("which", "who", "what office", "ano ang")
)
ABBREVIATIONS = (
    "a.y.",
    "no.",
    "st.",
    "dr.",
    "mr.",
    "ms.",
    "sr.",
    "a.m.",
    "p.m.",
    "e.g.",
    "i.e.",
    "vs.",
)
ASCII_WHITESPACE = " \t\n\r\f\v"
LINES = re.compile(r"[\n\r]+")
BREAK = re.compile(r"[.!?](?=[ \t\n\r\f\v]+[A-Z0-9])")
TIME = re.compile(
    r"(?<![0-9])[0-9]{1,2}(?::[0-9]{2})?[ ]?(?:a\.m\.|p\.m\.|am|pm|nn|noon|mn)"
    r"(?![a-z0-9])",
    re.IGNORECASE | re.ASCII,
)
MAX_QUOTE = 300
ELLIPSIS = "\u2026"


def _has_phrase(toks: list[str], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    return any(tuple(toks[i : i + n]) == phrase for i in range(len(toks) - n + 1))


def matched_time_phrases(question: str) -> list[tuple[str, ...]] | None:
    """Step 1: the matched time phrases, or None if not classified."""
    toks = tokens(question.lower())
    if any(_has_phrase(toks, p) for p in ENTITY_PHRASES):
        return None
    found = [p for p in TIME_PHRASES if _has_phrase(toks, p)]
    return found or None


def reduced_terms(question: str, phrases: list[tuple[str, ...]]) -> Terms:
    """Step 2: rank_v1's terms without the matched time phrases' tokens."""
    terms = question_terms(question)
    drop = {tok for p in phrases for tok in p}
    words = tuple(w for w in terms.words if w not in drop)
    return Terms(words, terms.dates, terms.numbers)


def admissible(terms: Terms, top: dict) -> bool:
    """Step 3."""
    if not terms.words:
        return False
    found = points(terms, top["title"].lower(), top["excerpt"].lower(), SYNONYMS_V3)
    return found == terms.possible


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _is_ascii_letter(ch: str) -> bool:
    return "a" <= ch <= "z" or "A" <= ch <= "Z"


def _ends_with_abbreviation(text: str) -> bool:
    """Case-insensitive (ASCII) abbreviation at the end, not inside a word."""
    for abbr in ABBREVIATIONS:
        n = len(abbr)
        if len(text) < n or text[-n:].translate(_ASCII_LOWER) != abbr:
            continue
        if len(text) == n or not _is_ascii_letter(text[-n - 1]):
            return True
    return False


def _split_line(line: str) -> list[str]:
    out, start = [], 0
    for match in BREAK.finditer(line):
        end = match.end()
        if _ends_with_abbreviation(line[:end]):
            continue
        out.append(line[start:end])
        start = end
    out.append(line[start:])
    return out


def sentences(top: dict) -> list[str]:
    """Step 4: the title, then the excerpt's sentences."""
    parts: list[str] = []
    for line in LINES.split(top["excerpt"]):
        parts += [s.strip(ASCII_WHITESPACE) for s in _split_line(line)]
    parts = [s for s in parts if s]
    if len(top["excerpt"]) == EXCERPT_CHARS and parts:
        parts = parts[:-1]
    title = top["title"].strip(ASCII_WHITESPACE)
    return ([title] if title else []) + parts


def _spans(text: str) -> list[tuple[int, int]]:
    _, _, dates = date_scan(text)
    times = TIME.finditer(text.translate(SPACE_TABLE))
    return [(s, e) for s, e, _ in dates] + [(m.start(), m.end()) for m in times]


def has_date_or_time(text: str) -> bool:
    """Step 5."""
    return bool(_spans(text))


def cut(sentence: str) -> str | None:
    """Step 7: the sentence cut to MAX_QUOTE code points, or None."""
    if len(sentence) <= MAX_QUOTE:
        return sentence
    spans = _spans(sentence)
    for i in range(MAX_QUOTE - 1, -1, -1):
        if sentence[i] == " " and not any(s < i < e for s, e in spans):
            quote = sentence[:i].rstrip(ASCII_WHITESPACE) + ELLIPSIS
            return quote if has_date_or_time(quote) else None
    return None


@dataclass(frozen=True)
class Extract:
    classified: bool
    words: tuple[str, ...] | None
    admissible: bool
    sentences: tuple[str, ...] | None
    guard_fired: bool
    quote: str | None  # before (c)'s note; None: no extract


def extract(question: str, results: list[dict]) -> Extract:
    """Steps 1-8 on contract-checked results (results[0] is the top)."""
    phrases = matched_time_phrases(question)
    if phrases is None or not results:
        return Extract(False, None, False, None, False, None)
    terms = reduced_terms(question, phrases)
    top = results[0]
    if not admissible(terms, top):
        return Extract(True, terms.words, False, None, False, None)
    found = tuple(sentences(top))
    best, best_points = None, -1
    for sentence in found:
        if not has_date_or_time(sentence):
            continue
        got = points(terms, sentence.lower(), "", SYNONYMS_V3)
        if got > best_points:
            best, best_points = sentence, got
    quote = None if best is None else cut(best)
    if quote is None:
        return Extract(True, terms.words, True, found, False, None)
    if guard(quote, results, question, []).fired:
        return Extract(True, terms.words, True, found, True, None)
    return Extract(True, terms.words, True, found, False, quote)


def source_text(top: dict) -> str:
    """(c)'s cited source for a quote: the quoted row."""
    return f"{top['title']}\n{top['excerpt']}"
