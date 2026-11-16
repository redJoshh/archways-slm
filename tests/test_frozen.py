"""The frozen FINAL configuration (accuracy-phase.md, section 3 "Then", step 1)."""

from pathlib import Path

from archways_assistant import assistant
from archways_assistant.frozen import FINAL, Config

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "assistant-ts" / "src" / "generated.ts"


def test_final_is_the_kept_set():
    # Kept: rank_v1, and_v4, strip_nf_v1, answer v1. Off: retry_v1, gate_v1,
    # excerpt_v2_centred, answer v4 (devlog 2026-11-14 to 2026-11-16).
    assert FINAL == Config(
        rank="rank_v1",
        matcher="and_v4",
        retry=None,
        excerpt=None,
        strip_nf=assistant.STRIP_NF_V1,
        answer_prompt="prompts/e2e_answer_v1.txt",
    )
    assert (ROOT / FINAL.answer_prompt).is_file()


def test_the_phone_defaults_are_generated_from_final():
    text = GENERATED.read_text(encoding="utf-8")
    for name, value in (
        ("PHONE_RANK", '"rank_v1"'),
        ("PHONE_MATCHER", '"and_v4"'),
        ("PHONE_RETRY", "null"),
        ("PHONE_EXCERPT", "null"),
        ("PHONE_STRIP_NF", '"strip_nf_v1"'),
        ("ANSWER_PROMPT_FILE", '"prompts/e2e_answer_v1.txt"'),
    ):
        assert f"export const {name} = {value};" in text


def test_python_flow_defaults_stay_the_baseline():
    # --verify-baseline and --config baseline rely on these defaults.
    import inspect

    from archways_assistant.feedindex import search_feed

    assert inspect.signature(assistant.flow).parameters["strip_nf"].default is None
    params = inspect.signature(search_feed).parameters
    assert params["rank"].default is None
    assert params["matcher"].default == "and_v3"
    assert params["excerpt"].default is None
