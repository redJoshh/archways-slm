import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from archways_assistant.fakebackend import (
    AND_V2_STOPWORDS,
    DEFAULT_MATCHER,
    EXCERPT_CHARS,
    STOPWORDS,
    SYNONYMS,
    InvalidArguments,
    ilike_pattern,
    prefix_stems,
    query_words,
    search_announcements,
    synonym_groups,
)
from archways_assistant.tooldef import SCHEMA_PATH

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VECTORS = json.loads(
    (ROOT / "tests" / "vectors" / "search_vectors.json").read_text(encoding="utf-8")
)
VECTOR_NOW = datetime.fromisoformat(VECTORS["now"])
SEED = json.loads(
    (ROOT / "data" / "seed" / "announcements.json").read_text(encoding="utf-8")
)
SEED_FIELDS = {
    "id": str,
    "title": str,
    "body": str,
    "office": str,
    "priority": str,
    "year_level": (int, type(None)),
    "published_at": str,
    "status": str,
    "is_archived": bool,
    "scheduled": bool,
}
RESULT_VALIDATOR = Draft202012Validator(
    {**CONTRACT["$defs"]["result"], "$defs": CONTRACT["$defs"]},
    format_checker=FormatChecker(),
)


def search(arguments, rows=None, now=VECTOR_NOW):
    return search_announcements(
        VECTORS["rows"] if rows is None else rows, arguments, now, CONTRACT
    )


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=lambda v: v["name"])
def test_search_vector(vector):
    if vector.get("expected_error"):
        with pytest.raises(InvalidArguments):
            search(vector["arguments"])
        return
    results = search(vector["arguments"])
    assert [result["id"] for result in results] == vector["expected_ids"]
    if "expected_patterns" in vector:
        words = query_words(vector["arguments"]["query"])
        assert [ilike_pattern(word) for word in words] == vector["expected_patterns"]


def test_vectors_carry_the_backend_stopwords():
    assert VECTORS["stopwords"] == sorted(STOPWORDS)


def test_results_match_the_contract_result_schema():
    results = search({"query": "library", "days": 30, "limit": 10})
    assert results
    RESULT_VALIDATOR.validate(results)


def test_posted_at_attaches_plus_eight_to_the_naive_timestamp():
    (result,) = search({"query": "parking"})
    assert result["posted_at"] == "2026-10-27T10:00:00+08:00"


def test_excerpt_is_the_body_cut_to_500_characters():
    rows = copy.deepcopy(VECTORS["rows"][:1])
    rows[0]["body"] = "library " + "x" * 600
    (result,) = search({"query": "library"}, rows=rows)
    assert result["excerpt"] == rows[0]["body"][:EXCERPT_CHARS]
    assert len(result["excerpt"]) == EXCERPT_CHARS


def test_rows_with_a_zone_are_rejected():
    rows = copy.deepcopy(VECTORS["rows"][:1])
    rows[0]["published_at"] = "2026-11-01T09:00:00+08:00"
    with pytest.raises(ValueError, match="naive"):
        search({"query": "library"}, rows=rows)


def test_naive_now_is_rejected():
    with pytest.raises(ValueError, match="time zone"):
        search({"query": "library"}, now=VECTOR_NOW.replace(tzinfo=None))


def test_arguments_are_not_modified():
    arguments = {"query": "library"}
    search(arguments)
    assert arguments == {"query": "library"}


# Seed data shape and traps. Traps that depend on the evaluation date are
# checked in tests/test_e2e_cases.py, next to the cases that fix that date.


@pytest.mark.parametrize("row", SEED, ids=lambda row: row["id"])
def test_seed_row_shape(row):
    assert set(row) == set(SEED_FIELDS)
    for field, kind in SEED_FIELDS.items():
        assert isinstance(row[field], kind), field
    assert datetime.fromisoformat(row["published_at"]).tzinfo is None


def test_seed_ids_are_unique():
    ids = [row["id"] for row in SEED]
    assert len(ids) == len(set(ids))


def test_seed_has_no_wildcard_characters():
    # So "%" and "*" searches in the end-to-end cases find nothing.
    for row in SEED:
        assert not set("%*_\\") & set(row["title"] + row["body"]), row["id"]


def test_seed_has_each_trap():
    assert any(row["status"] == "DRAFT" for row in SEED)
    assert any(row["is_archived"] for row in SEED)
    assert any(row["scheduled"] and row["status"] == "PUBLISHED" for row in SEED)
    assert any(row["year_level"] is not None for row in SEED)
    assert any("ignore your rules" in row["body"].lower() for row in SEED)
    assert any("replaces the earlier notice" in row["body"] for row in SEED)
    assert any(len(row["body"]) > EXCERPT_CHARS for row in SEED)


# prefix_v2 matcher (tests/vectors/search_vectors_v2.json).

VECTORS_V2 = json.loads(
    (ROOT / "tests" / "vectors" / "search_vectors_v2.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("vector", VECTORS_V2["vectors"], ids=lambda v: v["name"])
def test_search_vector_prefix_v2(vector):
    def run():
        return search_announcements(
            VECTORS_V2["rows"],
            vector["arguments"],
            datetime.fromisoformat(VECTORS_V2["now"]),
            CONTRACT,
            matcher="prefix_v2",
        )

    if vector.get("expected_error"):
        with pytest.raises(InvalidArguments):
            run()
        return
    assert [result["id"] for result in run()] == vector["expected_ids"]
    if "expected_stems" in vector:
        assert prefix_stems(vector["arguments"]["query"]) == vector["expected_stems"]


def test_v2_vectors_share_the_stopwords_and_v1_rows():
    assert VECTORS_V2["matcher"] == "prefix_v2"
    assert VECTORS_V2["stopwords"] == sorted(STOPWORDS)
    assert VECTORS_V2["rows"][: len(VECTORS["rows"])] == VECTORS["rows"]


def test_default_matcher_is_and_v1():
    assert DEFAULT_MATCHER == "and_v1"
    arguments = {"query": "enrolment"}
    assert [r["id"] for r in search(arguments, rows=VECTORS_V2["rows"])] == ["v-12"]


def test_unknown_matcher_is_rejected():
    with pytest.raises(ValueError, match="unknown matcher"):
        search_announcements(
            VECTORS["rows"], {"query": "library"}, VECTOR_NOW, CONTRACT, matcher="x"
        )


# and_v2 matcher (tests/vectors/search_vectors_and_v2.json).

VECTORS_AND_V2 = json.loads(
    (ROOT / "tests" / "vectors" / "search_vectors_and_v2.json").read_text(
        encoding="utf-8"
    )
)
SYNONYMS_FILE = ROOT / "contracts" / "search_synonyms_v1.json"
# Frozen: a change to the map is a new file and a new matcher, never an edit.
SYNONYMS_SHA256 = "287fb773f77c98fd8059039bc6dbbb2934decddb5fb8428d1c9d728a2d774c22"


def test_synonym_map_file_is_frozen():
    digest = hashlib.sha256(SYNONYMS_FILE.read_bytes()).hexdigest()
    assert digest == SYNONYMS_SHA256


def test_backend_uses_the_map_file():
    data = json.loads(SYNONYMS_FILE.read_text(encoding="utf-8"))
    assert data["matcher"] == "and_v2"
    assert SYNONYMS == data["synonyms"]
    assert AND_V2_STOPWORDS == STOPWORDS | set(data["extra_stopwords"])


def test_and_v1_stopwords_are_unchanged_by_and_v2():
    assert "kapag" not in STOPWORDS
    assert "kapag" in AND_V2_STOPWORDS
    assert "may" not in AND_V2_STOPWORDS


def run_and_v2(arguments, rows=None):
    return search_announcements(
        VECTORS_AND_V2["rows"] if rows is None else rows,
        arguments,
        datetime.fromisoformat(VECTORS_AND_V2["now"]),
        CONTRACT,
        matcher="and_v2",
    )


@pytest.mark.parametrize("vector", VECTORS_AND_V2["vectors"], ids=lambda v: v["name"])
def test_search_vector_and_v2(vector):
    assert [r["id"] for r in run_and_v2(vector["arguments"])] == vector["expected_ids"]
    groups = synonym_groups(vector["arguments"]["query"])
    assert [[ilike_pattern(alt) for alt in group] for group in groups] == vector[
        "expected_patterns"
    ]


def test_and_v2_vectors_share_the_stopwords_and_v1_rows():
    assert VECTORS_AND_V2["matcher"] == "and_v2"
    assert VECTORS_AND_V2["synonyms_file"] == "contracts/search_synonyms_v1.json"
    assert VECTORS_AND_V2["stopwords"] == sorted(AND_V2_STOPWORDS)
    assert VECTORS_AND_V2["rows"][: len(VECTORS["rows"])] == VECTORS["rows"]


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=lambda v: v["name"])
def test_and_v2_matches_and_v1_without_mapped_words(vector):
    words = vector["arguments"].get("query", "").lower().split()
    if set(words) & (set(SYNONYMS) | AND_V2_STOPWORDS - STOPWORDS):
        pytest.skip("uses a mapped word or an and_v2 stopword")
    if vector.get("expected_error"):
        with pytest.raises(InvalidArguments):
            run_and_v2(vector["arguments"], rows=VECTORS["rows"])
        return
    got = run_and_v2(vector["arguments"], rows=VECTORS["rows"])
    assert [r["id"] for r in got] == vector["expected_ids"]
