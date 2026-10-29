import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant.render import OLLAMA_TEMPLATE, render_gemma3

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
# Saved output of `ollama show gemma3:1b --template` (Ollama 0.40.13).
FIXTURE = ROOT / "tests" / "fixtures" / "ollama_gemma3_1b_template.txt"


def load_script(name: str):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_renderer_follows_the_saved_ollama_template():
    # Text mode, so a CRLF checkout still compares equal.
    assert FIXTURE.read_text(encoding="utf-8") == OLLAMA_TEMPLATE


def test_system_then_user_is_two_user_turns_then_an_open_model_turn():
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "U"},
    ]
    assert render_gemma3(messages) == (
        "<start_of_turn>user\nS<end_of_turn>\n"
        "<start_of_turn>user\nU<end_of_turn>\n"
        "<start_of_turn>model\n"
    )


def test_a_single_user_message():
    assert render_gemma3([{"role": "user", "content": "U"}]) == (
        "<start_of_turn>user\nU<end_of_turn>\n<start_of_turn>model\n"
    )


def test_a_last_assistant_message_is_left_open():
    messages = [
        {"role": "user", "content": "U"},
        {"role": "assistant", "content": "A"},
    ]
    assert render_gemma3(messages) == (
        "<start_of_turn>user\nU<end_of_turn>\n<start_of_turn>model\nA"
    )


def test_an_earlier_assistant_message_is_closed():
    messages = [
        {"role": "user", "content": "U1"},
        {"role": "assistant", "content": "A"},
        {"role": "user", "content": "U2"},
    ]
    assert render_gemma3(messages) == (
        "<start_of_turn>user\nU1<end_of_turn>\n"
        "<start_of_turn>model\nA<end_of_turn>\n"
        "<start_of_turn>user\nU2<end_of_turn>\n"
        "<start_of_turn>model\n"
    )


def test_content_is_not_trimmed():
    messages = [{"role": "user", "content": "  U\n\n"}]
    assert render_gemma3(messages) == (
        "<start_of_turn>user\n  U\n\n<end_of_turn>\n<start_of_turn>model\n"
    )


def test_unknown_roles_are_rejected_not_dropped():
    with pytest.raises(ValueError, match="unsupported role 'tool'"):
        render_gemma3([{"role": "tool", "content": "x"}])


def test_an_e2e_answer_call_renders_with_its_frozen_prompt():
    harness = load_script("probe_end_to_end")
    now = datetime.fromisoformat("2026-11-02T10:00:00+08:00")
    system = harness.load_prompt(harness.ANSWER_PROMPT, now, None)
    user = harness.announcements_message(
        "When is the career fair?", [{"id": "x-1", "title": "Career Fair"}]
    )
    text = render_gemma3(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
    assert text == (
        f"<start_of_turn>user\n{system}<end_of_turn>\n"
        f"<start_of_turn>user\n{user}<end_of_turn>\n"
        "<start_of_turn>model\n"
    )
    assert text.startswith("<start_of_turn>user\nYou are Archways AI")
    assert "Today is Monday, 2026-11-02" in text
    assert text.endswith("</announcements><end_of_turn>\n<start_of_turn>model\n")
