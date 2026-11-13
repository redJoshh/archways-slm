"""eval_heldout.py prints totals, the file hash and settings only, and writes nothing.

accuracy-phase.md, section 2. The cases here are invented; no real held-out
file is read.
"""

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from archways_assistant.e2escore import NOT_FOUND_MESSAGE

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "eval_heldout.py"
SECRET_ID = "secret-case-id-7f3a"
SECRET_QUESTION = "secret question text 9c1e"
SECRET_REPLY = "secret reply text 4b2d"

ROWS = [
    {
        "id": "18",
        "title": "Some title",
        "body": "Some body.",
        "office": "Some Office",
        "priority": "NORMAL",
        "year_level": None,
        "published_at": "2026-11-07T09:00:00",
        "status": "PUBLISHED",
        "is_archived": False,
        "scheduled": False,
    }
]


def load_script():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("eval_heldout", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def held_out_file(tmp_path: Path) -> Path:
    cases = [
        {
            "id": SECRET_ID,
            "question": SECRET_QUESTION,
            "now": "2030-01-01T00:00:00+08:00",  # must be ignored
            "source_ids": ["18"],
            "must_include": [["Some"]],
            "must_not_include": [],
            "expects_not_found": False,
        },
        {
            "id": SECRET_ID + "-trap",
            "question": SECRET_QUESTION + " trap",
            "source_ids": [],
            "must_include": [],
            "must_not_include": [],
            "expects_not_found": True,
        },
    ]
    path = tmp_path / "cases.jsonl"
    path.write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")
    return path


def patch(module, monkeypatch, run_case):
    monkeypatch.setattr(module, "load_sources", lambda: {"snapshot": ROWS})
    monkeypatch.setattr(module, "ollama_version", lambda client: "0.0.0")
    monkeypatch.setattr(module, "model_digest", lambda client, model: "digest")
    monkeypatch.setattr(module, "git_commit", lambda: "abc1234")
    monkeypatch.setattr(module, "tree_is_dirty", lambda: False)
    monkeypatch.setattr(module, "run_case", run_case)


def test_prints_only_settings_hash_and_totals(tmp_path, monkeypatch, capsys):
    module = load_script()
    path = held_out_file(tmp_path)
    seen_now = []

    def fake_run_case(client, model, case, prompts, rows, contract):
        seen_now.append(case["now"])
        return {
            "path": "not_found",
            "text": NOT_FOUND_MESSAGE,
            "results": [],
            "answer_reply": SECRET_REPLY,
            "query_reply": SECRET_REPLY,
        }

    patch(module, monkeypatch, fake_run_case)
    before = sorted(p.name for p in tmp_path.iterdir())
    monkeypatch.setattr(
        sys, "argv", ["eval_heldout.py", str(path), "--config", "baseline"]
    )
    module.main()
    out, err = capsys.readouterr()
    text = out + err
    for secret in (SECRET_ID, SECRET_QUESTION, SECRET_REPLY):
        assert secret not in text
    assert seen_now == [module.FIXED_NOW, module.FIXED_NOW]
    assert module.FIXED_NOW.isoformat() == "2026-11-14T10:00:00+08:00"
    lines = out.splitlines()
    assert lines[0].startswith("settings: ")
    assert '"fixed_now": "2026-11-14T10:00:00+08:00"' in lines[0]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert lines[1] == f"held-out file sha256 {digest}  cases 2"
    assert lines[2].startswith("HELD-OUT: cases 2  helpful 0/1")
    assert "traps_clean 1/1" in lines[2]
    assert lines[3].startswith("  paths: ")
    assert len(lines) == 4
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_a_failing_case_prints_no_value_and_no_totals(tmp_path, monkeypatch, capsys):
    module = load_script()

    def failing(client, model, case, prompts, rows, contract):
        raise ValueError(SECRET_QUESTION)

    patch(module, monkeypatch, failing)
    argv = ["eval_heldout.py", str(held_out_file(tmp_path)), "--config", "baseline"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as stop:
        module.main()
    out, err = capsys.readouterr()
    assert SECRET_QUESTION not in out + err + str(stop.value.code)
    assert "HELD-OUT:" not in out
    assert "case number 1 failed (ValueError)" in str(stop.value.code)


def test_only_the_baseline_config_exists_until_the_final_freeze():
    assert load_script().CONFIGS == ("baseline",)


def test_the_script_has_no_write_or_cache_call():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Attribute, ast.Name))
    }
    assert not names & {"write_text", "write_bytes", "open", "mkdir", "dump"}
