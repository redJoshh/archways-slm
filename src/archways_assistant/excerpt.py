"""The plain-text excerpt rule of search contract v2 (decided 2026-11-06).

Spring must build each result's excerpt from the stored body (sanitized
rich-text HTML) in this order:

1. Strip tags. A tag is "<" followed by a letter, "/" or "!", up to the
   next ">". Inline tags (INLINE_TAGS, the CMS editor's b/i/u/s/a) are
   removed; every other tag (p, div, br, li, ...) becomes one space, so
   block boundaries keep words apart. A "<" not starting a tag is text.
2. Decode character references, only with a closing ";":
   - named: the HTML5 table (html.entities.html5), e.g. &amp; &nbsp;
   - numeric: &#NNN; and &#xHH;. A code point of 0, a surrogate or above
     U+10FFFF becomes U+FFFD.
   Anything else (no ";", unknown name) stays as written. Decoding comes
   after stripping, so "&lt;b&gt;" is the text "<b>", never a tag.
3. Collapse whitespace: each run of WHITESPACE (ASCII whitespace and
   U+00A0, which &nbsp; decodes to) becomes one space; leading and
   trailing runs are dropped.
4. Cut to EXCERPT_CHARS code points (fakebackend.to_announcement does
   the cut).

This is an explicit spec, not "whatever a library's text() does": whether
Jsoup's Element.text() gives the same output is unverified.
"""

import html.entities
import re

INLINE_TAGS = frozenset({"a", "b", "strong", "i", "em", "u", "s", "strike"})
TAG = re.compile(r"<([A-Za-z/!])[^>]*>")
TAG_NAME = re.compile(r"</?([A-Za-z][A-Za-z0-9]*)")
REFERENCE = re.compile(r"&(#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);")
WHITESPACE = " \t\n\r\f\v" + chr(0xA0)
WHITESPACE_RUN = re.compile("[" + re.escape(WHITESPACE) + "]+")
REPLACEMENT = chr(0xFFFD)


def has_tags(body: str) -> bool:
    return TAG.search(body) is not None


def has_references(body: str) -> bool:
    return REFERENCE.search(body) is not None


def strip_tags(body: str) -> str:
    def replace(match: re.Match) -> str:
        name = TAG_NAME.match(match.group(0))
        return "" if name and name.group(1).lower() in INLINE_TAGS else " "

    return TAG.sub(replace, body)


def decode_references(text: str) -> str:
    def replace(match: re.Match) -> str:
        token = match.group(1)
        if token.startswith("#"):
            digits = token[1:]
            code = int(digits[1:], 16) if digits[:1] in ("x", "X") else int(digits)
            if code == 0 or 0xD800 <= code <= 0xDFFF or code > 0x10FFFF:
                return REPLACEMENT
            return chr(code)
        return html.entities.html5.get(token + ";", match.group(0))

    return REFERENCE.sub(replace, text)


def plain_text(body: str) -> str:
    """Steps 1-3: the body as plain text, before the cut."""
    text = decode_references(strip_tags(body))
    return WHITESPACE_RUN.sub(" ", text).strip(" ")
