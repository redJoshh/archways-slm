"""eval_flow.py --nothing-worse: accuracy-phase.md section 3, rule 4."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load():
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


def score(helpful=True, wrong=(), answered=True, correct=True, trap=False):
    return {
        "helpful": None if trap else helpful,
        "wrong": list(wrong),
        "answered": answered,
        "correct": correct,
        "trap": trap,
        "out_of_scope": False,
        "clean": (not answered) if trap else None,
        "unrelated_list": False,
        "path": "answer" if answered else "not_found",
    }


def run(tmp_path: Path, name: str, scores: dict) -> Path:
    path = tmp_path / name
    cases = [{"set": "s", "id": i, "score": s} for i, s in scores.items()]
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return path


def test_same_runs_pass(tmp_path, capsys):
    base = run(tmp_path, "a.json", {"c1": score(), "c2": score(helpful=False)})
    assert load().nothing_worse(base, base, set())


def test_a_new_unsafe_case_fails_even_if_totals_hold(tmp_path, capsys):
    base = run(
        tmp_path, "a.json", {"c1": score(wrong=["x"], helpful=False), "c2": score()}
    )
    new = run(
        tmp_path, "b.json", {"c1": score(), "c2": score(wrong=["y"], helpful=False)}
    )
    assert not load().nothing_worse(base, new, set())
    assert "new unsafe ['c2']" in capsys.readouterr().out


def test_a_helpful_drop_fails_and_each_regression_is_listed(tmp_path, capsys):
    base = run(tmp_path, "a.json", {"c1": score(), "c2": score()})
    new = run(
        tmp_path, "b.json", {"c1": score(helpful=False, correct=False), "c2": score()}
    )
    assert not load().nothing_worse(base, new, set())
    assert "helpful lost ['c1']" in capsys.readouterr().out


def test_a_swap_of_helpful_cases_passes_on_totals_but_is_listed(tmp_path, capsys):
    base = run(
        tmp_path, "a.json", {"c1": score(), "c2": score(helpful=False, correct=False)}
    )
    new = run(
        tmp_path, "b.json", {"c1": score(helpful=False, correct=False), "c2": score()}
    )
    assert load().nothing_worse(base, new, set())
    out = capsys.readouterr().out
    assert "helpful lost ['c1']" in out and "gained ['c2']" in out


def test_an_excluded_case_is_outside_the_check(tmp_path, capsys):
    base = run(tmp_path, "a.json", {"e2e-003": score(), "c2": score()})
    new = run(
        tmp_path,
        "b.json",
        {"e2e-003": score(wrong=["z"], helpful=False), "c2": score()},
    )
    assert load().nothing_worse(base, new, {"e2e-003"})
    assert "outside the check e2e-003" in capsys.readouterr().out
