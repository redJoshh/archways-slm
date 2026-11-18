"""Build contracts/search_synonyms_v3.json from the Taglish lexicon candidates.

Usage:
    uv run python scripts/build_taglish_lexicon.py [--words PATH] [--check]

Applies the pre-registered checks C1-C8 (docs/plans/v2-improvements.md,
"taglish_lexicon_v1 rule, pre-registered") to
contracts/taglish_lexicon_candidates_v1.json, over the snapshot and the seed
(the corpus) and the English word list (default
data/local/wordlists/words_alpha.txt, gitignored). Prints, per dropped term
or removed expansion, the check that removed it (term words only, never
announcement text). Writes search_synonyms_v3.json = v2's map + the
survivors; --check exits 1 if the committed file differs.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from archways_assistant.fakebackend import AND_V2_STOPWORDS
from archways_assistant.rank import RANK_STOPWORDS
from archways_assistant.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
CANDIDATES = CONTRACTS / "taglish_lexicon_candidates_v1.json"
V2 = CONTRACTS / "search_synonyms_v2.json"
V3 = CONTRACTS / "search_synonyms_v3.json"
SNAPSHOT = ROOT / "data" / "local" / "announcements_snapshot.json"
SEED = ROOT / "data" / "seed" / "announcements.json"
WORDS = ROOT / "data" / "local" / "wordlists" / "words_alpha.txt"
WORDS_SHA256 = "3ed0c94610d8bcf7c11bbb49c56aa49c7234d32b66824df91f554169e572da48"

KEY_SHAPE = re.compile(r"[a-z]{4,}")
MONTHS = frozenset(
    [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "enero",
        "pebrero",
        "marso",
        "abril",
        "mayo",
        "hunyo",
        "hulyo",
        "agosto",
        "setyembre",
        "oktubre",
        "nobyembre",
        "disyembre",
    ]
)
SUFFIXES = ("", "s", "es", "d", "ed", "ing", "er", "ers")
MIN_ALT_CHARS = 4
GENERIC_SHARE = 0.25
MAX_TERMS = 100
MIN_TERMS = 50


def alpha_tokens(text: str) -> list[str]:
    out, current = [], []
    for ch in text:
        if ch.isalpha():
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def occurrence_ok(text: str, at: int, alt: str) -> bool:
    """C5: the occurrence starts a token and only an allowed suffix follows."""
    if at > 0 and text[at - 1].isalpha():
        return False
    end = at + len(alt)
    suffix_end = end
    while suffix_end < len(text) and text[suffix_end].isalpha():
        suffix_end += 1
    return text[end:suffix_end] in SUFFIXES


def build(words_path: Path) -> tuple[dict, list[str]]:
    data = words_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != WORDS_SHA256:
        sys.exit("the English word list's SHA-256 differs from the recorded one")
    english = {w.strip() for w in data.decode("utf-8").splitlines() if w.strip()}
    v2 = json.loads(V2.read_text(encoding="utf-8"))
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))["terms"]
    snapshot = load_snapshot(SNAPSHOT).rows
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    corpus = [f"{r['title']}\n{r['body']}".lower() for r in snapshot + seed]
    snapshot_texts = [(r["title"].lower(), r["body"].lower()) for r in snapshot]
    tokens = {t for text in corpus for t in alpha_tokens(text)}
    stop = (
        set(AND_V2_STOPWORDS) | set(v2.get("extra_stopwords", [])) | set(RANK_STOPWORDS)
    )
    log, kept = [], {}
    for key, alts in candidates.items():
        if not KEY_SHAPE.fullmatch(key):
            log.append(f"drop {key}: C1 shape")
            continue
        if key in english or key in MONTHS:
            log.append(f"drop {key}: C2 English word list or month")
            continue
        if key in v2["synonyms"] or key in stop:
            log.append(f"drop {key}: C3 already a v2 key or a stopword")
            continue
        inside = sorted(t for t in tokens if key in t and t != key)
        if inside:
            log.append(f"drop {key}: C4 inside corpus tokens {inside[:5]}")
            continue
        survivors = []
        for alt in alts:
            if len(alt.replace(" ", "")) < MIN_ALT_CHARS:
                log.append(f"  {key}: remove '{alt}': C5 shorter than 4")
                continue
            bad = any(
                not occurrence_ok(text, m.start(), alt)
                for text in corpus
                for m in re.finditer(re.escape(alt), text)
            )
            if bad:
                log.append(f"  {key}: remove '{alt}': C5 inside another word")
                continue
            rows = sum(alt in t or alt in b for t, b in snapshot_texts)
            if rows > GENERIC_SHARE * len(snapshot_texts):
                log.append(
                    f"  {key}: remove '{alt}': C6 in {rows}/{len(snapshot_texts)} rows"
                )
                continue
            survivors.append(alt)
        if not survivors:
            log.append(f"drop {key}: C7 no expansion left")
            continue
        kept[key] = survivors
    if len(kept) > MAX_TERMS:
        for key in list(kept)[MAX_TERMS:]:
            log.append(f"drop {key}: C8 beyond the first {MAX_TERMS}")
        kept = dict(list(kept.items())[:MAX_TERMS])
    if len(kept) < MIN_TERMS:
        log.append(
            f"STOP: only {len(kept)} terms survive (C8 needs at least {MIN_TERMS})"
        )
    v3 = {
        "$comment": (
            "Frozen synonym map for the and_v5 matcher (v2 fix (e), "
            "docs/plans/v2-improvements.md 'taglish_lexicon_v1 rule, pre-registered'): "
            "search_synonyms_v2.json plus the Taglish lexicon v1 terms that survived "
            "checks C1-C8 (generated by scripts/build_taglish_lexicon.py). Never edit; "
            "a change is search_synonyms_v4.json."
        ),
        "name": "search_synonyms_v3",
        "matcher": "and_v5",
        "extra_stopwords": v2.get("extra_stopwords", []),
        "synonyms": {**v2["synonyms"], **kept},
    }
    return v3, log


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--words", type=Path, default=WORDS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    v3, log = build(args.words)
    for line in log:
        print(line)
    added = len(v3["synonyms"]) - len(json.loads(V2.read_text("utf-8"))["synonyms"])
    print(f"kept {added} lexicon terms")
    text = json.dumps(v3, ensure_ascii=False, indent=1) + "\n"
    if args.check:
        if not V3.exists() or V3.read_text(encoding="utf-8") != text:
            sys.exit(f"{V3.relative_to(ROOT)} is out of date")
        print(f"{V3.relative_to(ROOT)} is up to date")
        return
    if any(line.startswith("STOP") for line in log):
        sys.exit("not written: too few terms")
    V3.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {V3.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
