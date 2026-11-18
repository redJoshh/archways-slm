"""contradiction_v1 (v2 fix (a)): block a permission reply when a listed source prohibits.

The rule is docs/plans/v2-improvements.md, "contradiction_v1 rule,
pre-registered" (2026-11-18), checked by the hand-written
tests/vectors/contradiction_vectors.json. assistant-ts ports it
(src/contradiction.ts).

It runs only on a reply the guard passed (the "answer" path). It fires when
all three hold:

1. the question has a permission trigger phrase
2. a listed result's title + "\\n" + excerpt has a prohibition marker phrase
3. the reply asserts permission: its first token is yes/oo/opo, or a
   permission token has no negation among the (up to) 3 tokens before it

Tokens: the text lowercased, then maximal runs of and_v3 word characters; an
apostrophe (U+0027 or U+2019) between two word characters joins the token and
is written as U+0027. Phrases match as consecutive tokens.

Known limits (recorded with the decision, 2026-11-18): a reply that echoes a
Taglish permission question ("Pwede ...?") is blocked even when it then
states the prohibition (rules10 r02); only snapshot rows 19 and 29 use the
marker words.
"""

from archways_assistant.fakebackend import is_word_char

CONTRADICTION_V1 = "contradiction_v1"
CODE = "contradiction"
APOSTROPHES = ("'", "’")

TRIGGERS = (
    "can i",
    "can we",
    "can students",
    "may i",
    "may we",
    "is it allowed",
    "are we allowed",
    "am i allowed",
    "allowed ba",
    "pwede ba",
    "puwede ba",
    "pwede",
    "puwede",
    "bawal ba",
)
MARKERS = (
    "prohibited",
    "not allowed",
    "not permitted",
    "strictly prohibited",
    "strictly not allowed",
    "bawal",
    "forbidden",
    "banned",
    "must not",
)
YES_FIRST = ("yes", "oo", "opo")
PERMISSION = ("allowed", "permitted", "encouraged", "pwede", "puwede", "can")
NEGATIONS = ("not", "never", "no", "hindi", "bawal", "cannot", "can't")
NEGATION_WINDOW = 3


def tokens(text: str) -> list[str]:
    """The rule's tokens of text (see the module docstring)."""
    lowered = text.lower()
    out: list[str] = []
    current: list[str] = []
    for index, ch in enumerate(lowered):
        if is_word_char(ch):
            current.append(ch)
        elif (
            ch in APOSTROPHES
            and current
            and index + 1 < len(lowered)
            and is_word_char(lowered[index + 1])
        ):
            current.append("'")
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def has_phrase(words: list[str], phrase: str) -> bool:
    parts = phrase.split(" ")
    return any(
        words[start : start + len(parts)] == parts
        for start in range(len(words) - len(parts) + 1)
    )


def asserts_permission(reply: str) -> bool:
    words = tokens(reply)
    if words and words[0] in YES_FIRST:
        return True
    for index, word in enumerate(words):
        if word in PERMISSION:
            before = words[max(0, index - NEGATION_WINDOW) : index]
            if not any(token in NEGATIONS for token in before):
                return True
    return False


def fires(question: str, reply: str, results: list[dict]) -> bool:
    """Whether contradiction_v1 blocks this guard-passed reply."""
    question_words = tokens(question)
    if not any(has_phrase(question_words, p) for p in TRIGGERS):
        return False
    marked = False
    for result in results:
        words = tokens(f"{result['title']}\n{result['excerpt']}")
        if any(has_phrase(words, p) for p in MARKERS):
            marked = True
            break
    return marked and asserts_permission(reply)
