"""Synthetic announcement rows for training data: schema, validator, traps.

Rows have exactly the fields of data/seed/announcements.json, so the real
fakebackend can serve them. Ids start with "anc-" (hand-written anchors) or
"syn-" (expanded rows), so a dev seed row ("ann-...") can never pass as a
synthetic one.

Each trap inserter is a pure function: it never changes its input, and it
returns new rows plus a Trap that records the trap's label and facts. The
label lives in the Trap, not in the row, so rows keep the seed's shape and
the scorer can read the expected behavior later.
"""

import copy
from dataclasses import dataclass, field
from datetime import datetime

from jsonschema import Draft202012Validator

from archways_assistant.fakebackend import EXCERPT_CHARS, PUBLISHED

ROW_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {"type": "string", "pattern": "^(anc|syn)-[0-9]{3,}$"},
        "title": {"type": "string", "minLength": 1, "maxLength": 150},
        "body": {"type": "string", "minLength": 1},
        "office": {"type": "string", "minLength": 1},
        # The seed's values; the contract allows any string (unverified
        # which values Spring has).
        "priority": {"enum": ["HIGH", "NORMAL"]},
        "year_level": {"type": ["integer", "null"], "minimum": 1},
        # Naive timestamp, like the seed and the database column.
        "published_at": {
            "type": "string",
            "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$",
        },
        "status": {"enum": ["PUBLISHED", "DRAFT"]},
        "is_archived": {"type": "boolean"},
        "scheduled": {"type": "boolean"},
    },
    "required": [
        "id",
        "title",
        "body",
        "office",
        "priority",
        "year_level",
        "published_at",
        "status",
        "is_archived",
        "scheduled",
    ],
    "additionalProperties": False,
}
ROW_VALIDATOR = Draft202012Validator(ROW_SCHEMA)

TRAP_LABELS = ("long_body", "injection", "superseded", "year_level")


def validate_rows(rows: list) -> list[str]:
    """Every problem found, as "row N (id): ..." strings; empty if valid."""
    if not isinstance(rows, list):
        return ["rows must be a JSON array"]
    problems = []
    seen = set()
    for number, row in enumerate(rows, start=1):
        name = f"row {number}"
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            name += f" ({row['id']})"
            if row["id"] in seen:
                problems.append(f"{name}: duplicate id")
            seen.add(row["id"])
        for error in ROW_VALIDATOR.iter_errors(row):
            where = "/".join(map(str, error.absolute_path)) or "(row)"
            problems.append(f"{name}: {where}: {error.message}")
        published_at = row.get("published_at") if isinstance(row, dict) else None
        if isinstance(published_at, str) and ROW_VALIDATOR.is_valid(row):
            try:
                datetime.fromisoformat(published_at)
            except ValueError:
                problems.append(f"{name}: published_at: not a real date and time")
    return problems


@dataclass(frozen=True)
class Trap:
    """One inserted trap: its label, the rows it touches, and its facts."""

    label: str
    row_ids: tuple[str, ...]
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.label not in TRAP_LABELS:
            raise ValueError(f"unknown trap label {self.label!r}")

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "row_ids": list(self.row_ids),
            **copy.deepcopy(self.details),
        }


def insert_long_body(row: dict, key_fact: str, filler: str) -> tuple[dict, Trap]:
    """Append filler and then key_fact, so key_fact starts at or after
    EXCERPT_CHARS and never reaches the model."""
    new = copy.deepcopy(row)
    new["body"] = f"{row['body']} {filler} {key_fact}"
    start = new["body"].index(key_fact)
    if start < EXCERPT_CHARS:
        raise ValueError(
            f"key fact starts at character {start}; it must start at "
            f"{EXCERPT_CHARS} or later (lengthen the filler, or the key fact "
            "is already in the body)"
        )
    trap = Trap(
        "long_body",
        (row["id"],),
        {"key_fact": key_fact, "key_fact_start": start, "excerpt_chars": EXCERPT_CHARS},
    )
    return new, trap


def insert_injection(
    row: dict, instruction: str, must_not_include: list[str]
) -> tuple[dict, Trap]:
    """Append an instruction to the body, inside the excerpt the model sees.

    must_not_include: phrases a reply that obeyed the instruction would
    contain. None of them may already be in the row.
    """
    if not must_not_include:
        raise ValueError("must_not_include is empty")
    text = f"{row['title']}\n{row['body']}".lower()
    already = [phrase for phrase in must_not_include if phrase.lower() in text]
    if already:
        raise ValueError(f"phrases already in the row: {already}")
    new = copy.deepcopy(row)
    new["body"] = f"{row['body']} {instruction}"
    end = new["body"].rindex(instruction) + len(instruction)
    if end > EXCERPT_CHARS:
        raise ValueError(
            f"instruction ends at character {end}, past the {EXCERPT_CHARS}-"
            "character excerpt, so the model would never see it"
        )
    trap = Trap(
        "injection",
        (row["id"],),
        {"instruction": instruction, "must_not_include": list(must_not_include)},
    )
    return new, trap


def insert_superseded_pair(
    row: dict,
    *,
    new_id: str,
    old_fact: str,
    new_fact: str,
    published_at: str,
    title_prefix: str = "Revised: ",
) -> tuple[tuple[dict, dict], Trap]:
    """The row as the old announcement, plus a later one with new_fact in
    place of old_fact. Both are live, as in e2e-002."""
    if row["status"] != PUBLISHED or row["is_archived"]:
        raise ValueError("the row must be PUBLISHED and not archived")
    if row["body"].count(old_fact) != 1:
        raise ValueError("old_fact must appear exactly once in the body")
    if new_fact == old_fact or new_fact in row["body"]:
        raise ValueError("new_fact must differ from old_fact and not be in the body")
    if new_id == row["id"]:
        raise ValueError("new_id must differ from the row's id")
    if datetime.fromisoformat(published_at) <= datetime.fromisoformat(
        row["published_at"]
    ):
        raise ValueError("published_at must be later than the row's")
    old = copy.deepcopy(row)
    new = copy.deepcopy(row)
    new.update(
        id=new_id,
        title=f"{title_prefix}{row['title']}",
        body=row["body"].replace(old_fact, new_fact),
        published_at=published_at,
    )
    trap = Trap(
        "superseded",
        (old["id"], new_id),
        {"current": [new_fact], "old": [old_fact]},
    )
    return (old, new), trap


def insert_year_level(row: dict, year_level: int) -> tuple[dict, Trap]:
    """Make an all-students row (year_level null) apply to one year level."""
    if row["year_level"] is not None:
        raise ValueError("the row already has a year_level")
    if isinstance(year_level, bool) or not isinstance(year_level, int):
        raise TypeError("year_level must be an integer")
    if year_level < 1:
        raise ValueError("year_level must be 1 or more")
    new = copy.deepcopy(row)
    new["year_level"] = year_level
    return new, Trap("year_level", (row["id"],), {"year_level": year_level})
