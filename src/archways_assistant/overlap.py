"""Lexical overlap between texts: exact copies and near-copies.

Used by tests/test_prompts.py (prompt examples against eval questions) and
scripts/check_overlap.py (any JSONL file against a protected file).

Both checks are lexical. They catch copies and near-copies that reuse the
same words; a paraphrase in different words passes unnoticed.
"""

import re

# Texts sharing at least this share of words (Jaccard over lowercase
# letter/digit words) count as paraphrases.
MAX_WORD_OVERLAP = 0.3


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def word_overlap(a: str, b: str) -> float:
    a_words, b_words = words(a), words(b)
    union = a_words | b_words
    return len(a_words & b_words) / len(union) if union else 0.0


def normalize(text: str) -> str:
    """Lowercase with runs of whitespace collapsed to one space."""
    return " ".join(text.lower().split())


def is_copy(protected: str, candidate: str) -> bool:
    """The normalized protected text appears inside the normalized candidate."""
    needle = normalize(protected)
    return bool(needle) and needle in normalize(candidate)


def is_near_copy(protected: str, candidate: str) -> bool:
    return word_overlap(protected, candidate) >= MAX_WORD_OVERLAP


def overlap_kind(protected: str, candidate: str) -> str | None:
    """ "exact", "paraphrase" or None (exact wins when both apply)."""
    if is_copy(protected, candidate):
        return "exact"
    if is_near_copy(protected, candidate):
        return "paraphrase"
    return None
