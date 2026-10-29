import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from archways_assistant.overlap import (
    MAX_WORD_OVERLAP,
    is_copy,
    overlap_kind,
    word_overlap,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_overlap.py"
DEV = ROOT / "evals" / "dev_questions.jsonl"
E2E = ROOT / "evals" / "e2e_cases.jsonl"
SEED = ROOT / "data" / "seed" / "announcements.json"
SEED_ROWS = json.loads(SEED.read_text(encoding="utf-8"))
# A deliberate near-copy of ann-001's body: reworded, not a substring.
NEAR_COPY_BODY = (
    "Second-term online enrollment opens November 9, 2026 and closes "
    "November 20, 2026. Students settle assessed fees before enlisting "
    "subjects in the student portal."
)
UNRELATED_BODY = (
    "The swimming pool reopens after repairs. Bring your ID and a towel; "
    "lockers are first come, first served."
)
E2E_001 = "When does online enrollment for the second term close?"
# A deliberate near-copy of e2e-001: reworded, not a substring.
NEAR_COPY = "When will the online enrollment for the second term close?"
UNRELATED = "Where can I borrow a laptop charger on campus?"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return path


def test_threshold_is_unchanged():
    assert MAX_WORD_OVERLAP == 0.3


def test_the_near_copy_is_not_a_substring_but_is_flagged():
    assert not is_copy(E2E_001, NEAR_COPY)
    assert word_overlap(E2E_001, NEAR_COPY) >= MAX_WORD_OVERLAP
    assert overlap_kind(E2E_001, NEAR_COPY) == "paraphrase"


def test_a_copy_inside_a_longer_text_is_exact_despite_case_and_spacing():
    candidate = "Student asked:  " + E2E_001.upper().replace(" ", "\n  ") + " Thanks."
    assert overlap_kind(E2E_001, candidate) == "exact"


def test_an_unrelated_question_is_not_flagged():
    assert overlap_kind(E2E_001, UNRELATED) is None


def test_empty_texts_do_not_divide_by_zero():
    assert word_overlap("", "?!") == 0.0
    assert overlap_kind("", "anything") is None


def test_every_dev_question_flags_itself():
    result = run(str(DEV), str(DEV))
    count = sum(1 for line in DEV.read_text(encoding="utf-8").splitlines() if line)
    assert result.returncode == 1
    assert f"protected items checked: {count}; candidate items checked: {count};" in (
        result.stdout
    )
    assert f"(exact {count}," in result.stdout


def test_script_flags_the_near_copy_and_shows_only_the_candidate(tmp_path):
    candidates = write_jsonl(
        tmp_path / "train.jsonl",
        [
            {"id": "train-1", "question": NEAR_COPY},
            {"id": "train-2", "question": UNRELATED},
        ],
    )
    result = run(str(E2E), str(candidates), "--show-candidates")
    assert result.returncode == 1
    assert "candidate items checked: 2;" in result.stdout
    assert "train-1 [paraphrase]: " + NEAR_COPY in result.stdout
    assert "train-2" not in result.stdout
    assert E2E_001 not in result.stdout
    assert "e2e-001" not in result.stdout


def test_default_output_is_counts_only(tmp_path):
    candidates = write_jsonl(
        tmp_path / "train.jsonl", [{"id": "train-1", "question": NEAR_COPY}]
    )
    result = run(str(E2E), str(candidates))
    assert result.returncode == 1
    # The near-copy also overlaps other enrollment questions, so only the
    # shape of the line is fixed, not the pair count.
    line, share = result.stdout.splitlines()
    assert re.fullmatch(
        r"protected items checked: 34; candidate items checked: 1; "
        r"flagged pairs: [1-9]\d* \(exact 0, paraphrase [1-9]\d*; "
        r"paraphrase = word overlap >= 0\.3\)",
        line,
    )
    assert (
        share == f"  {candidates}: flagged items 1/1 (100%) (over 10%: review by hand)"
    )


def test_clean_candidates_exit_zero_across_several_files(tmp_path):
    first = write_jsonl(tmp_path / "a.jsonl", [{"id": "a", "question": UNRELATED}])
    second = write_jsonl(
        tmp_path / "b.jsonl", [{"id": "b", "question": "Is the gym open on Sundays?"}]
    )
    result = run(str(E2E), str(first), str(second))
    assert result.returncode == 0, result.stdout
    assert "candidate items checked: 2; flagged pairs: 0 " in result.stdout


def test_field_names_are_arguments(tmp_path):
    candidates = write_jsonl(
        tmp_path / "train.jsonl", [{"key": "t1", "prompt": "x " + E2E_001}]
    )
    result = run(
        str(E2E),
        str(candidates),
        "--candidate-field",
        "prompt",
        "--candidate-id-field",
        "key",
        "--show-candidates",
    )
    assert result.returncode == 1
    assert "t1 [exact" in result.stdout


@pytest.mark.parametrize(
    "line, error", [("{not json", "not valid JSON"), ('{"q": "secret"}', "no string")]
)
def test_a_bad_protected_line_is_reported_without_its_text(tmp_path, line, error):
    protected = tmp_path / "protected.jsonl"
    protected.write_text('{"question": "fine"}\n' + line + "\n", encoding="utf-8")
    candidates = write_jsonl(tmp_path / "c.jsonl", [{"question": UNRELATED}])
    result = run(str(protected), str(candidates))
    assert result.returncode == 2
    assert "line 2" in result.stderr and error in result.stderr
    assert "secret" not in result.stderr + result.stdout
    assert "not json" not in result.stderr + result.stdout


def write_array(path: Path, records: list[dict]) -> Path:
    path.write_text(json.dumps(records, indent=1), encoding="utf-8")
    return path


def test_the_body_near_copy_is_not_a_substring_but_is_flagged():
    body = SEED_ROWS[0]["body"]
    assert SEED_ROWS[0]["id"] == "ann-001"
    assert not is_copy(body, NEAR_COPY_BODY)
    assert overlap_kind(body, NEAR_COPY_BODY) == "paraphrase"


def test_seed_bodies_are_checkable_as_a_json_array(tmp_path):
    candidates = write_array(
        tmp_path / "synth.json",
        [
            {"id": "syn-1", "body": NEAR_COPY_BODY},
            {"id": "syn-2", "body": UNRELATED_BODY},
        ],
    )
    result = run(
        str(SEED),
        str(candidates),
        "--protected-field",
        "body",
        "--candidate-field",
        "body",
        "--show-candidates",
    )
    assert result.returncode == 1
    assert (
        f"protected items checked: {len(SEED_ROWS)}; candidate items checked: 2;"
        in (result.stdout)
    )
    assert f"  {candidates}: flagged items 1/2 (50%) (over 10%: review by hand)" in (
        result.stdout
    )
    assert "syn-1 [paraphrase]" in result.stdout
    assert "syn-2" not in result.stdout
    assert "ann-001" not in result.stdout
    assert SEED_ROWS[0]["body"] not in result.stdout


def test_every_seed_title_flags_itself():
    result = run(
        str(SEED), str(SEED), "--protected-field", "title", "--candidate-field", "title"
    )
    assert result.returncode == 1
    assert f"flagged items {len(SEED_ROWS)}/{len(SEED_ROWS)} (100%)" in result.stdout


def test_a_share_at_ten_percent_is_not_marked_for_review(tmp_path):
    records = [{"id": "q0", "question": NEAR_COPY}] + [
        {"id": f"q{n}", "question": f"Is the gym open on day {n}?"}
        for n in range(1, 10)
    ]
    candidates = write_jsonl(tmp_path / "train.jsonl", records)
    result = run(str(E2E), str(candidates))
    assert f"  {candidates}: flagged items 1/10 (10%)" in result.stdout.splitlines()


@pytest.mark.parametrize(
    "content, error",
    [('[{"body": "fine"}, {"title": "secret"}]', "item 2: no string"), ("[{", "array")],
)
def test_a_bad_protected_array_is_reported_without_its_text(tmp_path, content, error):
    protected = tmp_path / "protected.json"
    protected.write_text(content, encoding="utf-8")
    candidates = write_jsonl(tmp_path / "c.jsonl", [{"body": UNRELATED_BODY}])
    result = run(
        str(protected),
        str(candidates),
        "--protected-field",
        "body",
        "--candidate-field",
        "body",
    )
    assert result.returncode == 2
    assert error in result.stderr
    assert "secret" not in result.stderr + result.stdout


def test_the_tests_never_name_the_held_out_file():
    assert "heldout" + "_questions" not in Path(__file__).read_text(encoding="utf-8")
