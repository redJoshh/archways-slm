"""window_v1 (docs/plans/window-fallback.md): the 30-day window as a fallback.

- The hand-written tests/vectors/window_fallback_vectors.json (section 4.4).
- Invariance at the fixed evaluation dates (sections 4.1 to 4.3): the
  structural snapshot check, the snapshot title-word sweep and the dev
  replay. Each is skipped when its gitignored input (data/local/) is absent.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from archways_assistant.fakebackend import InvalidArguments, is_visible, published_at
from archways_assistant.feedindex import feed_row, search_feed, search_feed_window
from archways_assistant.frozen import FINAL
from archways_assistant.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads(
    (ROOT / "tests" / "vectors" / "window_fallback_vectors.json").read_text("utf-8")
)
CONTRACT = json.loads(
    (ROOT / "contracts" / "search_announcements.schema.json").read_text("utf-8")
)
NOW = datetime.fromisoformat(DATA["now"])
ROWS = [feed_row(detail)[0] for detail in DATA["details"]]
CASES = DATA["cases"]
# The FINAL search (frozen.py) that the phone runs window_v1 with.
SEARCH = {"rank": FINAL.rank, "matcher": FINAL.matcher, "excerpt": FINAL.excerpt}

LOCAL = ROOT / "data" / "local"
SNAPSHOT = LOCAL / "announcements_snapshot.json"
SEED = ROOT / "data" / "seed" / "announcements.json"
DEV_RUN = LOCAL / "runs" / "strip_nf-1.json"
# The fixed evaluation instants: flow13 (dev), the v1 and the v2 held-out runs.
EVAL_NOWS = (
    "2026-11-10T10:00:00+08:00",
    "2026-11-14T10:00:00+08:00",
    "2026-11-17T10:00:00+08:00",  # the v2 held-out fixed now
)


def run(rows, arguments, now, question, **kw):
    return search_feed_window(
        rows, arguments, now, CONTRACT, question=question, **SEARCH, **kw
    )


def test_the_vectors_match_the_final_search_and_the_plan():
    assert (DATA["rank"], DATA["matcher"]) == (FINAL.rank, FINAL.matcher)
    assert FINAL.excerpt is None
    assert DATA["window"] == "window_v1" and DATA["fallback_days"] == 365
    assert CONTRACT["$defs"]["arguments"]["properties"]["days"]["maximum"] == 30


@pytest.mark.parametrize("case", CASES, ids=[c["name"].split(":")[0] for c in CASES])
def test_window_fallback_vectors(case):
    if not case["ok"]:
        with pytest.raises(InvalidArguments):
            run(ROWS, case["arguments"], NOW, case["question"])
        return
    results, fell_back = run(ROWS, case["arguments"], NOW, case["question"])
    assert [r["id"] for r in results] == case["expected_ids"]
    assert fell_back == case["fell_back"]


def test_window_off_is_the_plain_search():
    case = next(c for c in CASES if c["name"].startswith("W2:"))
    assert run(ROWS, case["arguments"], NOW, case["question"], window=None) == (
        [],
        False,
    )


def test_an_unknown_window_version_is_rejected():
    with pytest.raises(ValueError):
        run(ROWS, {"query": "x", "days": 30}, NOW, "x", window="window_v2")


def test_a_fallback_result_keeps_the_announcement_shape():
    case = next(c for c in CASES if c["name"].startswith("W2:"))
    results, _ = run(ROWS, case["arguments"], NOW, case["question"])
    plain = search_feed(
        ROWS,
        {"query": "kite", "days": 30},
        NOW + timedelta(days=-2),
        CONTRACT,
        question="kite festival",
        **SEARCH,
    )
    assert results == plain  # at now - 2 days, row 3 is inside the 30-day window


@pytest.mark.parametrize(
    "change",
    [{"status": "DRAFT"}, {"is_archived": True}],
    ids=["unpublished", "archived"],
)
def test_the_fallback_never_reaches_an_invisible_row(change):
    row = dict(feed_row(DATA["details"][2])[0])  # row 3, 31 days old
    row.update(change)
    assert run([row], {"query": "kite", "days": 30}, NOW, "kite festival") == (
        [],
        True,
    )


# Sections 4.1 to 4.3: no dev or held-out result can change.


def snapshot_rows() -> list[dict]:
    if not SNAPSHOT.exists():
        pytest.skip("the gitignored snapshot is absent")
    return load_snapshot(SNAPSHOT).rows


@pytest.mark.parametrize("now", EVAL_NOWS)
def test_no_visible_snapshot_row_is_older_than_30_days_at_the_eval_dates(now):
    """4.1: so the fallback can only run when nothing is visible in 30 days,
    and then it finds nothing either. That covers every query, the held-out
    questions included, without reading them."""
    instant = datetime.fromisoformat(now)
    visible = [row for row in snapshot_rows() if is_visible(row, instant)]
    assert visible
    assert all(published_at(row) >= instant - timedelta(days=30) for row in visible)


def title_words(rows: list[dict]) -> list[str]:
    words = {
        word.lower()
        for row in rows
        for word in re.findall(r"[^\W\d_]{3,}", row["title"])
    }
    return sorted(words)


@pytest.mark.parametrize("now", EVAL_NOWS)
def test_snapshot_title_word_sweep_is_unchanged(now):
    """4.2: every title word as a query, with days 1, 7, 14 and 30."""
    rows = snapshot_rows()
    instant = datetime.fromisoformat(now)
    words = title_words(rows)
    assert len(words) > 100
    for word in words:
        for days in (1, 7, 14, 30):
            arguments = {"query": word, "days": days}
            plain = search_feed(
                rows, arguments, instant, CONTRACT, question=word, **SEARCH
            )
            assert run(rows, arguments, instant, word)[0] == plain, (word, days)


def test_dev_replay_is_unchanged():
    """4.3: the frozen dev run's saved arguments, case by case, at their now."""
    if not DEV_RUN.exists():
        pytest.skip("the gitignored frozen dev run is absent")
    dev = json.loads(DEV_RUN.read_text("utf-8"))
    header = dev["header"]
    assert header["matcher"] == FINAL.matcher
    sources = {"seed": json.loads(SEED.read_text("utf-8"))}
    if SNAPSHOT.exists():
        sources["snapshot"] = load_snapshot(SNAPSHOT).rows
    set_source = {"e2e34": "seed", "taglish10": "seed", "flow13": "snapshot"}
    searched = fell_back_ids = 0
    for case in dev["cases"]:
        if not isinstance(case["arguments"], dict):
            continue
        source = set_source[case["set"]]
        if source not in sources:
            continue
        now = datetime.fromisoformat(case["now"])
        results, fell_back = run(
            sources[source], case["arguments"], now, case["question"]
        )
        assert results == case["results"], case["id"]
        searched += 1
        fell_back_ids += fell_back
    assert searched >= 44
    print(f"dev replay: {searched} searches identical, {fell_back_ids} fell back")
