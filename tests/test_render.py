import hashlib
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

from archways_assistant.render import (
    OLLAMA_TEMPLATE,
    QWEN3_OLLAMA_TEMPLATE,
    QWEN3_STOP,
    render_gemma3,
    render_qwen3,
    render_qwen3_example,
)

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


# --- qwen3:0.6b -------------------------------------------------------------

# Saved `template` field of /api/show for qwen3:0.6b (Ollama 0.40.14).
QWEN3_FIXTURE = ROOT / "tests" / "fixtures" / "ollama_qwen3_0_6b_template.txt"
QWEN3_FIXTURE_SHA256 = (
    "ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4"
)
SYSTEM_USER = [
    {"role": "system", "content": "S"},
    {"role": "user", "content": "U"},
]


def test_qwen3_renderer_follows_the_saved_ollama_template():
    assert QWEN3_FIXTURE.read_text(encoding="utf-8") == QWEN3_OLLAMA_TEMPLATE


def test_qwen3_template_fixture_is_pinned():
    # Fails if the fixture is re-saved from another Ollama or model version:
    # then render_qwen3() must be re-derived and the evidence rerun.
    digest = hashlib.sha256(QWEN3_FIXTURE.read_bytes()).hexdigest()
    assert digest == QWEN3_FIXTURE_SHA256


def test_qwen3_system_then_user_with_thinking_off():
    assert render_qwen3(SYSTEM_USER) == (
        "<|im_start|>system\n\nS<|im_end|>\n"
        "<|im_start|>user\nU /no_think<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def test_qwen3_system_turn_has_a_blank_line_after_the_role():
    assert render_qwen3(SYSTEM_USER).startswith("<|im_start|>system\n\nS")


def test_qwen3_no_think_goes_on_the_user_turn_before_im_end():
    text = render_qwen3(SYSTEM_USER)
    assert text.count(" /no_think") == 1
    assert "U /no_think<|im_end|>\n" in text


def test_qwen3_prompt_ends_with_the_empty_think_block():
    assert render_qwen3(SYSTEM_USER).endswith(
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def test_qwen3_has_no_start_of_text_token():
    text = render_qwen3(SYSTEM_USER)
    assert text.startswith("<|im_start|>")
    assert "<|endoftext|>" not in text
    assert "<bos>" not in text


def test_qwen3_content_is_not_trimmed():
    messages = [
        {"role": "system", "content": " S\n"},
        {"role": "user", "content": "\nU  "},
    ]
    assert render_qwen3(messages) == (
        "<|im_start|>system\n\n S\n<|im_end|>\n"
        "<|im_start|>user\n\nU   /no_think<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


@pytest.mark.parametrize(
    "roles",
    [
        ["user"],
        ["system"],
        ["user", "system"],
        ["system", "user", "user"],
        ["system", "user", "assistant"],
        ["system", "tool"],
        [],
    ],
)
def test_qwen3_rejects_every_other_shape(roles):
    messages = [{"role": role, "content": "x"} for role in roles]
    with pytest.raises(ValueError, match="expected roles"):
        render_qwen3(messages)


def test_qwen3_rejects_an_empty_system_message():
    with pytest.raises(ValueError, match="empty system"):
        render_qwen3([{"role": "system", "content": ""}, SYSTEM_USER[1]])


def test_qwen3_stop_strings():
    assert QWEN3_STOP == ("<|im_end|>", "<|im_start|>")


def test_qwen3_training_example_is_prompt_then_reply_and_im_end():
    prompt, target = render_qwen3_example(SYSTEM_USER, "A.")
    assert prompt == render_qwen3(SYSTEM_USER)
    assert target == "A.<|im_end|>"
    # What the model emits after the prompt, up to and including its stop.
    assert prompt + target == (
        "<|im_start|>system\n\nS<|im_end|>\n"
        "<|im_start|>user\nU /no_think<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\nA.<|im_end|>"
    )


@pytest.mark.parametrize(
    "reply", ["", "a<|im_end|>", "<|im_start|>", "<think>x</think>a", "a</think>"]
)
def test_qwen3_training_example_rejects_bad_replies(reply):
    with pytest.raises(ValueError):
        render_qwen3_example(SYSTEM_USER, reply)


def test_qwen3_e2e_answer_and_query_calls_render_with_their_frozen_prompts():
    harness = load_script("probe_end_to_end")
    now = datetime.fromisoformat("2026-11-02T10:00:00+08:00")
    question = "When is the career fair?"
    results = [
        {
            "id": "x-1",
            "title": "Career Fair",
            "excerpt": "Room <b>.",
            "office": "OSA",
            "priority": "normal",
            "year_level": None,
            "posted_at": "2026-11-01T09:00:00+08:00",
        }
    ]
    for prompt_path, user in (
        (harness.ANSWER_PROMPT, harness.announcements_message(question, results)),
        (
            harness.ANSWER_PROMPT_V2,
            harness.compact_announcements_message(question, results),
        ),
        (harness.QUERY_PROMPT, question),
    ):
        system = harness.load_prompt(prompt_path, now, None)
        text = render_qwen3(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        assert text == (
            f"<|im_start|>system\n\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user} /no_think<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )
        assert "Today is Monday, 2026-11-02" in text
    assert r"Room \u003cb>." in harness.compact_announcements_message(question, results)
