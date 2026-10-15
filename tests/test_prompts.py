from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def test_prompt_mode_reuses_system_v1_rules_exactly():
    rules = (PROMPTS / "system_v1.txt").read_bytes()
    prompt_mode = (PROMPTS / "system_v1_prompt_mode.txt").read_bytes()
    assert prompt_mode.startswith(rules)
