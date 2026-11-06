"""The contract v2 plain-text excerpt rule, on hand-worked strings."""

import json
from pathlib import Path

import pytest

from archways_assistant.excerpt import has_references, has_tags, plain_text

ROOT = Path(__file__).resolve().parents[1]
NBSP = chr(0xA0)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Plain text stays.", "Plain text stays."),
        ("<p>One</p><p>Two</p>", "One Two"),
        ("Line<br>break<br/>and<br />more", "Line break and more"),
        ("<ul><li>a</li><li>b</li></ul>", "a b"),
        ('<div style="text-align: center">Centred</div>', "Centred"),
        ("un<b>der</b>l<i>in</i>e<u>d</u> <s>x</s><strike>y</strike>", "underlined xy"),
        ("<STRONG>Bold</STRONG><EM>it</EM>", "Boldit"),
        (
            'Go <a href="https://x.example" rel="noopener noreferrer">here</a>.',
            "Go here.",
        ),
        ("<blockquote>Q</blockquote>A", "Q A"),
        ("Before<!-- note -->after", "Before after"),
        ("Unknown<span>tag</span>s", "Unknown tag s"),
        # Decoding after stripping: escaped markup is text, not a tag.
        ("&lt;b&gt;not bold&lt;/b&gt;", "<b>not bold</b>"),
        ("a &amp; b", "a & b"),
        ("x&nbsp;&nbsp;y", "x y"),
        ("&#65;&#x42;&#X43;", "ABC"),
        ("&#x1F600;", chr(0x1F600)),
        (
            "&#0;|&#xD800;|&#x110000;",
            chr(0xFFFD) + "|" + chr(0xFFFD) + "|" + chr(0xFFFD),
        ),
        # Only with a closing ";", and only known names.
        ("&amp no semicolon", "&amp no semicolon"),
        ("&bogus; stays", "&bogus; stays"),
        ("AT&T", "AT&T"),
        # "<" that does not start a tag is text.
        ("1 < 2 and 3 <= 4", "1 < 2 and 3 <= 4"),
        ("<3 you", "<3 you"),
        # Whitespace: runs of ASCII whitespace and U+00A0 become one space.
        ("  a \t\n\r b" + NBSP + NBSP + "c\f\v ", "a b c"),
        ("<p> padded </p>", "padded"),
        # Other Unicode spaces are kept.
        ("a" + chr(0x2003) + "b", "a" + chr(0x2003) + "b"),
        ("", ""),
    ],
)
def test_plain_text(body, expected):
    assert plain_text(body) == expected


def test_detectors():
    assert has_tags("<p>x</p>") and not has_tags("1 < 2")
    assert has_references("a&nbsp;b") and not has_references("AT&T")


def test_seed_bodies_are_already_plain():
    # So fakebackend's body[:500] already follows the rule on the seed.
    seed = json.loads(
        (ROOT / "data" / "seed" / "announcements.json").read_text("utf-8")
    )
    assert all(plain_text(row["body"]) == row["body"] for row in seed)
