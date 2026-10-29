"""Check candidate files for copies and near-copies of a protected file.

Usage: uv run python scripts/check_overlap.py PROTECTED CANDIDATE [CANDIDATE ...]
    [--protected-field question] [--candidate-field question]
    [--candidate-id-field id] [--show-candidates]

Each file is JSONL (one object per line) or, if it starts with "[", a JSON
array of objects, such as data/seed/announcements.json. To check
announcement text, run it once per field (--protected-field title
--candidate-field title, then body).

Every candidate text is compared with every protected text, using
archways_assistant.overlap (the same check tests/test_prompts.py uses):
- exact: the normalized protected text appears inside the candidate text
- paraphrase: the two share at least MAX_WORD_OVERLAP of their words

Both checks are lexical: they catch near-copies, not every paraphrase.

By default it prints only counts: protected items checked, candidate items
checked, flagged pairs, then the share of flagged items per candidate file.
A share over REVIEW_SHARE is marked for review by hand. --show-candidates also prints each flagged
candidate's file, id and text. It never prints protected text or ids, and
an invalid protected line or item is reported by its number only, so the
protected file can be one that must stay unseen.

Exits 1 if any pair is flagged, 2 on bad input, else 0.
"""

import argparse
import json
import sys
from pathlib import Path

from archways_assistant.overlap import MAX_WORD_OVERLAP, overlap_kind

# A candidate file with more than this share of flagged items is reviewed by
# hand with --show-candidates (flagged items are dropped by default).
REVIEW_SHARE = 0.10


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(2)


def read_records(path: Path):
    """(where, record) per item. Errors name the line or item, never quote it."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        fail(f"Cannot read {path}: {type(error).__name__}")
    if text.lstrip().startswith("["):
        try:
            records = json.loads(text)
        except ValueError:
            fail(f"{path}: not a valid JSON array")
        return [(f"{path}, item {n}", r) for n, r in enumerate(records, start=1)]
    items = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append((f"{path}, line {number}", json.loads(line)))
        except ValueError:
            fail(f"{path}, line {number}: not valid JSON")
    return items


def read_texts(path: Path, field: str, id_field: str | None):
    """(id, text) per item; the id falls back to the file and line or item."""
    items = []
    for where, record in read_records(path):
        text = record.get(field) if isinstance(record, dict) else None
        if not isinstance(text, str):
            fail(f"{where}: no string field {field!r}")
        item_id = record.get(id_field) if id_field else None
        items.append((str(item_id) if item_id is not None else where, text))
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("protected", type=Path)
    parser.add_argument("candidates", type=Path, nargs="+")
    parser.add_argument("--protected-field", default="question")
    parser.add_argument("--candidate-field", default="question")
    parser.add_argument(
        "--candidate-id-field",
        default="id",
        help="shown with --show-candidates (default id; file and line if missing)",
    )
    parser.add_argument(
        "--show-candidates",
        action="store_true",
        help="print flagged candidate ids and text (never protected ones)",
    )
    args = parser.parse_args()

    protected = [
        text for _, text in read_texts(args.protected, args.protected_field, None)
    ]
    checked = 0
    flagged = {"exact": 0, "paraphrase": 0}
    shown = []
    per_file = []
    for path in args.candidates:
        items = read_texts(path, args.candidate_field, args.candidate_id_field)
        flagged_items = 0
        for item_id, text in items:
            checked += 1
            kinds = [overlap_kind(p, text) for p in protected]
            for kind in kinds:
                if kind:
                    flagged[kind] += 1
            found = sorted({kind for kind in kinds if kind})
            if found:
                flagged_items += 1
                shown.append(f"  {path} {item_id} [{', '.join(found)}]: {text}")
        per_file.append((path, flagged_items, len(items)))

    total = sum(flagged.values())
    print(
        f"protected items checked: {len(protected)}; "
        f"candidate items checked: {checked}; "
        f"flagged pairs: {total} (exact {flagged['exact']}, "
        f"paraphrase {flagged['paraphrase']}; "
        f"paraphrase = word overlap >= {MAX_WORD_OVERLAP})"
    )
    for path, flagged_items, items in per_file:
        share = flagged_items / items if items else 0.0
        review = (
            f" (over {REVIEW_SHARE:.0%}: review by hand)"
            if share > REVIEW_SHARE
            else ""
        )
        print(f"  {path}: flagged items {flagged_items}/{items} ({share:.0%}){review}")
    if args.show_candidates and shown:
        print("Flagged candidates:")
        print("\n".join(shown))
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
