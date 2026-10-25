import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from archways_assistant.formatschema import build_format_schema
from archways_assistant.tooldef import SCHEMA_PATH

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"
DEV_QUESTIONS = [
    json.loads(line)["question"]
    for line in (ROOT / "evals" / "dev_questions.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
E2E_QUESTIONS = [
    json.loads(line)["question"]
    for line in (ROOT / "evals" / "e2e_cases.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
V4 = (PROMPTS / "system_v4_schema_mode.txt").read_text(encoding="utf-8")
E2E_QUERY = (PROMPTS / "e2e_query_v1.txt").read_text(encoding="utf-8")
# An e2e query example is a "Student: ..." line followed by its JSON line.
E2E_QUERY_EXAMPLES = re.findall(r"^Student: (.+)\n(\{.*\})$", E2E_QUERY, re.MULTILINE)
# An example is a "User: ..." line followed by the expected JSON output line.
V4_EXAMPLES = re.findall(r"^User: (.+)\n(\{.*\})$", V4, re.MULTILINE)
# Example inputs sharing at least this share of words with a dev question
# count as paraphrases.
MAX_WORD_OVERLAP = 0.3


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def word_overlap(a: str, b: str) -> float:
    a_words, b_words = words(a), words(b)
    return len(a_words & b_words) / len(a_words | b_words)


def test_prompt_mode_reuses_system_v1_rules_exactly():
    rules = (PROMPTS / "system_v1.txt").read_bytes()
    prompt_mode = (PROMPTS / "system_v1_prompt_mode.txt").read_bytes()
    assert prompt_mode.startswith(rules)


def test_v3_prompt_mode_reuses_system_v3_rules_exactly():
    rules = (PROMPTS / "system_v3.txt").read_bytes()
    prompt_mode = (PROMPTS / "system_v3_prompt_mode.txt").read_bytes()
    assert prompt_mode.startswith(rules)


@pytest.mark.parametrize("path", sorted(PROMPTS.glob("*.txt")), ids=lambda p: p.name)
def test_no_prompt_contains_a_dev_question(path):
    text = " ".join(path.read_text(encoding="utf-8").lower().split())
    for question in DEV_QUESTIONS + E2E_QUESTIONS:
        assert " ".join(question.lower().split()) not in text


def test_e2e_query_examples_match_the_arguments_schema():
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(contract["$defs"]["arguments"])
    assert E2E_QUERY_EXAMPLES
    for _, output in E2E_QUERY_EXAMPLES:
        assert validator.is_valid(json.loads(output)), output


@pytest.mark.parametrize("example", [inp for inp, _ in E2E_QUERY_EXAMPLES])
def test_e2e_query_examples_are_not_eval_paraphrases(example):
    for question in DEV_QUESTIONS + E2E_QUESTIONS:
        assert word_overlap(example, question) < MAX_WORD_OVERLAP, question


def test_v4_is_for_schema_mode_only():
    # Schema mode needs no {tool_definition}; without it, the probe refuses
    # to run v4 in --format-mode none.
    assert "{today}" in V4
    assert "{tool_definition}" not in V4


def test_v4_shows_both_output_shapes():
    assert '{"name": "search_announcements", "arguments": {' in V4
    assert '{"reply": "..."}' in V4


def test_v4_has_three_to_five_examples():
    assert 3 <= len(V4_EXAMPLES) <= 5


def test_v4_examples_match_the_format_schema():
    contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(build_format_schema(contract))
    for _, output in V4_EXAMPLES:
        assert validator.is_valid(json.loads(output)), output


def test_v4_examples_include_a_search_and_a_reply():
    outputs = [json.loads(output) for _, output in V4_EXAMPLES]
    assert any("name" in output for output in outputs)
    assert any("reply" in output for output in outputs)


@pytest.mark.parametrize("example", [inp for inp, _ in V4_EXAMPLES])
def test_v4_examples_are_not_dev_question_paraphrases(example):
    for question in DEV_QUESTIONS:
        assert word_overlap(example, question) < MAX_WORD_OVERLAP, question
