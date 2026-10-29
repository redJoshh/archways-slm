"""Check candidate JSONL files for copies and near-copies of a protected file.

Usage: uv run python scripts/check_overlap.py PROTECTED CANDIDATE [CANDIDATE ...]
    [--protected-field question] [--candidate-field question]
    [--candidate-id-field id] [--show-candidates]

Every candidate text is compared with every protected text, using
archways_assistant.overlap (the same check tests/test_prompts.py uses):
- exact: the normalized protected text appears inside the candidate text
- paraphrase: the two share at least MAX_WORD_OVERLAP of their words

Both checks are lexical: they catch near-copies, not every paraphrase.

By default it prints only counts: protected items checked, candidate items
checked, flagged pairs. --show-candidates also prints each flagged
candidate's file, id and text. It never prints protected text or ids, and
an invalid protected line is reported by line number only, so the
protected file can be one that must stay unseen.

Exits 1 if any pair is flagged, 2 on bad input, else 0.
"""

import argparse
import json
import sys
from pathlib import Path

from archways_assistant.overlap import MAX_WORD_OVERLAP, overlap_kind


def read_texts(path: Path, field: str, id_field: str | None):
    """(id, text) per non-blank line. Errors name the line, never quote it."""
    items = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        print(f"Cannot read {path}: {type(error).__name__}", file=sys.stderr)
        sys.exit(2)
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{path}, line {number}"
        try:
            record = json.loads(line)
        except ValueError:
            print(f"{where}: not valid JSON", file=sys.stderr)
            sys.exit(2)
        text = record.get(field) if isinstance(record, dict) else None
        if not isinstance(text, str):
            print(f"{where}: no string field {field!r}", file=sys.stderr)
            sys.exit(2)
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
    for path in args.candidates:
        for item_id, text in read_texts(
            path, args.candidate_field, args.candidate_id_field
        ):
            checked += 1
            kinds = [overlap_kind(p, text) for p in protected]
            for kind in kinds:
                if kind:
                    flagged[kind] += 1
            found = sorted({kind for kind in kinds if kind})
            if found:
                shown.append(f"  {path} {item_id} [{', '.join(found)}]: {text}")

    total = sum(flagged.values())
    print(
        f"protected items checked: {len(protected)}; "
        f"candidate items checked: {checked}; "
        f"flagged pairs: {total} (exact {flagged['exact']}, "
        f"paraphrase {flagged['paraphrase']}; "
        f"paraphrase = word overlap >= {MAX_WORD_OVERLAP})"
    )
    if args.show_candidates and shown:
        print("Flagged candidates:")
        print("\n".join(shown))
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
