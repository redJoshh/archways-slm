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
    (line,) = result.stdout.splitlines()
    assert re.fullmatch(
        r"protected items checked: 34; candidate items checked: 1; "
        r"flagged pairs: [1-9]\d* \(exact 0, paraphrase [1-9]\d*; "
        r"paraphrase = word overlap >= 0\.3\)",
        line,
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


def test_the_tests_never_name_the_held_out_file():
    assert "heldout" + "_questions" not in Path(__file__).read_text(encoding="utf-8")
