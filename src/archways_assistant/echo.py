"""echo_v1 (v2 fix (b)): a reply that only restates the question becomes answer_not_found.

The rule is docs/plans/v2-improvements.md, "echo_v1 rule, pre-registered"
(2026-11-18), checked by the hand-written tests/vectors/echo_vectors.json.
assistant-ts ports it (src/echo.ts).

On a reply the guard passed (and contradiction_v1 didn't block), with
rank_v1's terms of the question and of the reply, each content word replaced
by the matcher's plural_alternative when it has one, it fires when both hold:

1. the reply's dates and numbers are subsets of the question's
2. at most 2 distinct normalised reply words are not normalised question words

Recorded risks: a correct answer whose new content is 1-2 words (a two-word
office, a bare "Yes.") or a yes/no restatement counts as an echo.
"""

from archways_assistant.fakebackend import plural_alternative
from archways_assistant.rank import question_terms

ECHO_V1 = "echo_v1"
CODE = "echo"
MAX_NEW_WORDS = 2


def normalised(words: tuple[str, ...]) -> set[str]:
    return {plural_alternative(word) or word for word in words}


def is_echo(question: str, reply: str) -> bool:
    """Whether echo_v1 treats this guard-passed reply as answer_not_found."""
    asked = question_terms(question)
    said = question_terms(reply)
    if not (said.dates <= asked.dates and said.numbers <= asked.numbers):
        return False
    return len(normalised(said.words) - normalised(asked.words)) <= MAX_NEW_WORDS
