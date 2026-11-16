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

from archways_assistant import assistant
from archways_assistant.e2escore import NOT_FOUND_MESSAGE
from archways_assistant.fakebackend import to_announcement

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


def test_the_two_configs_are_baseline_and_final():
    assert load_script().CONFIGS == ("baseline", "final")


def run_config(tmp_path, monkeypatch, capsys, config, *extra):
    module = load_script()
    seen = []

    def fake_run_case(client, model, case, prompts, rows, contract, **options):
        seen.append((case["now"], prompts["answer"], options))
        return {
            "path": "not_found",
            "text": NOT_FOUND_MESSAGE,
            "results": [],
            "answer_reply": SECRET_REPLY,
            "query_reply": SECRET_REPLY,
            "arguments": None,
        }

    patch(module, monkeypatch, fake_run_case)
    path = held_out_file(tmp_path)
    argv = ["eval_heldout.py", str(path), "--config", config, *extra]
    monkeypatch.setattr(sys, "argv", argv)
    module.main()
    out, err = capsys.readouterr()
    return module, seen, out, err


def test_final_runs_the_frozen_set_with_the_same_four_lines(
    tmp_path, monkeypatch, capsys
):
    module, seen, out, err = run_config(tmp_path, monkeypatch, capsys, "final")
    v1 = (ROOT / "prompts" / "e2e_answer_v1.txt").read_text(encoding="utf-8")
    final = {
        "rank": "rank_v1",
        "matcher": "and_v4",
        "retry": None,
        "excerpt": None,
        "strip_nf": "strip_nf_v1",
    }
    assert seen == [(module.FIXED_NOW, v1, final)] * 2
    for secret in (SECRET_ID, SECRET_QUESTION, SECRET_REPLY):
        assert secret not in out + err
    lines = out.splitlines()
    assert len(lines) == 4
    settings = json.loads(lines[0].removeprefix("settings: "))
    assert settings["config"] == "final"
    assert settings["fixed_now"] == "2026-11-14T10:00:00+08:00"
    assert {k: settings[k] for k in final} == final
    assert settings["prompts"]["answer"][0] == "e2e_answer_v1.txt"
    assert lines[1].startswith("held-out file sha256 ")
    assert lines[2].startswith("HELD-OUT: cases 2")
    assert lines[3].startswith("  paths: ")


def test_baseline_is_unchanged_by_the_final_config(tmp_path, monkeypatch, capsys):
    _, seen, out, _ = run_config(tmp_path, monkeypatch, capsys, "baseline")
    assert [options for _, _, options in seen] == [{}, {}]
    settings = json.loads(out.splitlines()[0].removeprefix("settings: "))
    assert settings["matcher"] == "and_v3"
    assert not {"rank", "retry", "excerpt", "strip_nf"} & set(settings)


def test_final_writes_the_private_report_too(tmp_path, monkeypatch, capsys):
    outside = tmp_path / "report.txt"
    _, _, out, _ = run_config(
        tmp_path, monkeypatch, capsys, "final", "--private-report", str(outside)
    )
    assert len(out.splitlines()) == 4
    assert SECRET_QUESTION in outside.read_text(encoding="utf-8")


WRITES = {"write_text", "write_bytes", "open", "mkdir", "dump", "write"}


def write_names(node: ast.AST) -> set[str]:
    return {
        n.attr if isinstance(n, ast.Attribute) else n.id
        for n in ast.walk(node)
        if isinstance(n, (ast.Attribute, ast.Name))
    } & WRITES


def test_the_only_write_is_the_private_report():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    writer = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "write_private_report"
    ]
    assert len(writer) == 1 and write_names(writer[0]) == {"open", "write"}
    rest = [node for node in tree.body if node is not writer[0]]
    assert all(not write_names(node) for node in rest)


# --- --private-report (amendment of 2026-11-14) -------------------------------


def answering(client, model, case, prompts, rows, contract):
    found = [to_announcement(ROWS[0])]
    text = (
        assistant.ANSWER_LABEL
        + assistant.ANSWER_LABEL_SEPARATOR
        + SECRET_REPLY
        + assistant.ANSWER_LIST_SEPARATOR
        + assistant.results_list(found)
    )
    return {
        "path": "answer",
        "text": text,
        "results": found,
        "arguments": {"query": "q"},
    }


def run_main(module, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["eval_heldout.py", *argv])
    module.main()


def test_without_the_option_nothing_is_written(tmp_path, monkeypatch, capsys):
    module = load_script()
    patch(module, monkeypatch, answering)

    def no_write(path, blocks):
        raise AssertionError("wrote a report without --private-report")

    monkeypatch.setattr(module, "write_private_report", no_write)
    path = held_out_file(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    run_main(module, monkeypatch, str(path), "--config", "baseline")
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert len(capsys.readouterr().out.splitlines()) == 4


def test_the_report_outside_the_repo_has_question_reply_and_flags(
    tmp_path, monkeypatch, capsys
):
    module = load_script()
    patch(module, monkeypatch, answering)
    path = held_out_file(tmp_path)
    report = tmp_path / "review" / "report.txt"
    report.parent.mkdir()
    run_main(
        module,
        monkeypatch,
        str(path),
        "--config",
        "baseline",
        "--private-report",
        str(report),
    )
    out = capsys.readouterr().out
    # The printed lines are unchanged: four, with no case text and no report line.
    assert len(out.splitlines()) == 4
    for secret in (SECRET_ID, SECRET_QUESTION, SECRET_REPLY, str(report)):
        assert secret not in out
    text = report.read_text(encoding="utf-8")
    assert f"=== {SECRET_ID} ===" in text
    assert f"question: {SECRET_QUESTION}" in text
    assert SECRET_REPLY in text
    # Flags and reason codes per case: the answerable case misses "Some",
    # and the trap got an AI answer.
    assert "AI_NOT_CORRECT" in text and "missing:Some" in text
    assert "NOT_CLEAN" in text
    assert text.count("=== ") == 2


@pytest.mark.parametrize(
    "inside",
    [
        lambda: ROOT / "report.txt",
        lambda: ROOT / "data" / "local" / "report.txt",
        lambda: Path(str(ROOT).upper()) / "report.txt",
        lambda: ROOT / "data" / ".." / "report.txt",
        lambda: Path("report.txt"),  # relative, resolved against the repo cwd
    ],
)
def test_a_report_inside_the_repo_is_refused_before_any_run(
    tmp_path, monkeypatch, inside
):
    module = load_script()

    def never(*args):
        raise AssertionError("ran a case although the report path was refused")

    patch(module, monkeypatch, never)
    monkeypatch.chdir(ROOT)
    target = inside()
    path = held_out_file(tmp_path)
    with pytest.raises(SystemExit) as stop:
        run_main(
            module,
            monkeypatch,
            str(path),
            "--config",
            "baseline",
            "--private-report",
            str(target),
        )
    assert "outside the repository" in str(stop.value.code)
    assert not (ROOT / "report.txt").exists()
    assert not (ROOT / "data" / "local" / "report.txt").exists()


def test_an_existing_report_file_is_refused(tmp_path, monkeypatch):
    module = load_script()
    patch(module, monkeypatch, answering)
    existing = tmp_path / "old.txt"
    existing.write_text("keep", encoding="utf-8")
    path = held_out_file(tmp_path)
    with pytest.raises(SystemExit) as stop:
        run_main(
            module,
            monkeypatch,
            str(path),
            "--config",
            "baseline",
            "--private-report",
            str(existing),
        )
    assert "must not exist" in str(stop.value.code)
    assert existing.read_text(encoding="utf-8") == "keep"


def test_a_failed_run_writes_no_report(tmp_path, monkeypatch):
    module = load_script()

    def failing(*args):
        raise ValueError(SECRET_QUESTION)

    patch(module, monkeypatch, failing)
    report = tmp_path / "report.txt"
    with pytest.raises(SystemExit):
        run_main(
            module,
            monkeypatch,
            str(held_out_file(tmp_path)),
            "--config",
            "baseline",
            "--private-report",
            str(report),
        )
    assert not report.exists()


def test_the_repo_check_ignores_case(monkeypatch):
    """Windows paths are case-insensitive: a repo path in other case still matches."""
    module = load_script()
    monkeypatch.setattr(module, "REPO", Path(str(ROOT).upper()))
    with pytest.raises(SystemExit) as stop:
        module.private_report_path(str(ROOT / "report.txt"))
    assert "outside the repository" in str(stop.value.code)
