import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from archways_assistant.fakebackend import (
    EXCERPT_CHARS,
    STORED_ZONE,
    is_visible,
    published_at,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    json.loads(line)
    for line in (ROOT / "evals" / "e2e_cases.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
SEED = {
    row["id"]: row
    for row in json.loads(
        (ROOT / "data" / "seed" / "announcements.json").read_text(encoding="utf-8")
    )
}
NOW = datetime.fromisoformat(CASES[0]["now"])
CASE_FIELDS = {
    "id": str,
    "question": str,
    "now": str,
    "source_ids": list,
    "must_include": list,
    "must_not_include": list,
    "expects_not_found": bool,
}


def visible_text(row_id: str) -> str:
    """What the model can see of a row: title and excerpt."""
    row = SEED[row_id]
    return f"{row['title']}\n{row['body'][:EXCERPT_CHARS]}".lower()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_shape(case):
    optional = {"note", "exclusion", "superseded", "wrong_claims", "label"}
    assert set(case) - optional == set(CASE_FIELDS)
    for field, kind in CASE_FIELDS.items():
        assert isinstance(case[field], kind), field
    assert case.get("exclusion") in (None, "outdated", "injection")
    if "exclusion" in case:
        assert case["must_not_include"]
    assert all(isinstance(group, list) and group for group in case["must_include"])


def test_case_ids_are_unique():
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))


def test_every_case_uses_the_same_fixed_now():
    assert {case["now"] for case in CASES} == {"2026-11-02T10:00:00+08:00"}
    assert NOW.utcoffset() == STORED_ZONE.utcoffset(None)
    assert f"{NOW:%A}" == "Monday"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_sources_exist_and_are_visible_within_30_days(case):
    for row_id in case["source_ids"]:
        row = SEED[row_id]
        assert is_visible(row, NOW), row_id
        assert published_at(row) >= NOW - timedelta(days=30), row_id


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["must_include"]],
    ids=lambda c: c["id"],
)
def test_expected_answers_are_in_the_source_excerpts(case):
    text = "\n".join(visible_text(row_id) for row_id in case["source_ids"])
    for group in case["must_include"]:
        assert any(option.lower() in text for option in group), group


def test_not_found_cases_expect_nothing_to_include():
    for case in CASES:
        if case["expects_not_found"]:
            assert case["must_include"] == [], case["id"]


def test_seed_traps_hold_at_the_fixed_now():
    rows = list(SEED.values())
    # Draft, archived and future-scheduled rows are never visible.
    hidden = [row for row in rows if not is_visible(row, NOW)]
    assert {row["status"] for row in hidden} >= {"DRAFT", "PUBLISHED"}
    assert any(row["is_archived"] for row in hidden)
    assert any(published_at(row) > NOW for row in hidden)
    # One visible row is older than the 30-day maximum window.
    assert any(
        is_visible(row, NOW) and published_at(row) < NOW - timedelta(days=30)
        for row in rows
    )


def test_labelled_exclusions_are_in_the_source_excerpts():
    # A stale or injected phrase is one the model can see in what it retrieves.
    for case in CASES:
        if "exclusion" in case:
            text = "\n".join(visible_text(row_id) for row_id in SEED)
            assert any(p.lower() in text for p in case["must_not_include"]), case["id"]


def test_superseded_dates_come_from_the_new_and_old_rows():
    (case,) = [case for case in CASES if "superseded" in case]
    assert case["id"] == "e2e-002"
    current, old = case["superseded"]["current"], case["superseded"]["old"]
    assert any(date.lower() in visible_text("ann-003") for date in current)
    assert any(date.lower() in visible_text("ann-002") for date in old)
    assert not any(date.lower() in visible_text("ann-003") for date in old)


def test_retrieval_regression_cases():
    added = [case for case in CASES if case.get("label")]
    assert [case["id"] for case in added] == [f"e2e-{n:03d}" for n in range(25, 35)]
    assert {case["label"] for case in added} == {"added after diagnosis: retrieval"}
    assert sum(case["expects_not_found"] for case in added) == 2
    for case in added:
        assert case["source_ids"] or case["expects_not_found"], case["id"]


def test_late_deadline_is_only_after_the_excerpt():
    body = SEED["ann-004"]["body"]
    assert body.index("December 4") > EXCERPT_CHARS
    assert "december 4" not in visible_text("ann-004")


def test_superseding_row_is_newer_than_the_row_it_replaces():
    assert published_at(SEED["ann-003"]) > published_at(SEED["ann-002"])
    assert "replaces the earlier notice" in SEED["ann-003"]["body"]


def test_over_long_case_is_over_the_query_limit():
    assert any(len(case["question"]) > 200 for case in CASES)


def test_wildcard_cases_exist():
    questions = [case["question"] for case in CASES]
    assert any('"*"' in question for question in questions)
    assert any('"%"' in question for question in questions)
