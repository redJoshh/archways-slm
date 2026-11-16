"""Answer prompt v4 (accuracy-phase.md, section 3 (f)): v1 plus one sentence.

The sentence was written at pre-registration and is never changed after a
run; v4 is frozen by hash. eval_flow.py runs it only with --answer-prompt v4.
"""

import hashlib
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant import assistant
from archways_assistant.e2escore import NOT_FOUND_MESSAGE

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
V1 = ROOT / "prompts" / "e2e_answer_v1.txt"
V4 = ROOT / "prompts" / "e2e_answer_v4.txt"
# Verbatim from accuracy-phase.md, section 3 (f).
SENTENCE = (
    "Write the not-found sentence only if none of the announcements answers "
    "the question; if one does, even if it is not the first, answer from that one."
)
V4_SHA256 = "84eb2bd06e15ed42f3045de1edb60138d47a7e879a63ddddce1e09df8abc1bdf"
NOW = datetime.fromisoformat("2026-11-02T10:00:00+08:00")


def load_eval_flow():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "eval_flow", SCRIPTS / "eval_flow.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_the_sentence_is_in_the_plan_verbatim():
    plan = (ROOT / "docs" / "plans" / "accuracy-phase.md").read_text(encoding="utf-8")
    assert f'> "{SENTENCE}"' in plan


def test_v4_is_v1_plus_exactly_that_sentence():
    v1 = V1.read_bytes()
    v4 = V4.read_bytes()
    added = f" {SENTENCE}".encode()
    assert v4.count(added) == 1
    assert v4.replace(added, b"") == v1
    assert SENTENCE.encode() not in v1


def test_v4_is_frozen():
    assert hashlib.sha256(V4.read_bytes()).hexdigest() == V4_SHA256


def test_v4_keeps_the_exact_not_found_message_and_the_date():
    text = V4.read_text(encoding="utf-8")
    assert NOT_FOUND_MESSAGE in text
    assert assistant.fill_prompt(text, NOW).count("Monday, 2026-11-02") == 1


def test_v4_system_turn_is_only_the_sentence_longer_than_v1():
    v1 = assistant.fill_prompt(V1.read_text(encoding="utf-8"), NOW)
    v4 = assistant.fill_prompt(V4.read_text(encoding="utf-8"), NOW)
    assert v4.replace(f" {SENTENCE}", "") == v1


def test_eval_flow_defaults_to_v1_and_offers_v4():
    module = load_eval_flow()
    assert module.ANSWER_PROMPTS == {"v1": V1, "v4": V4}
    assert module.ANSWER_PROMPT == V1


def test_verify_baseline_refuses_v4(monkeypatch, tmp_path):
    module = load_eval_flow()
    argv = [
        "eval_flow.py",
        "--out",
        str(ROOT / "data" / "local" / "runs" / "never-written.json"),
        "--verify-baseline",
        str(tmp_path / "base.json"),
        "--answer-prompt",
        "v4",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as raised:
        module.main()
    assert raised.value.code == 2
