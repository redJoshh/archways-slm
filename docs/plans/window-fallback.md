# Plan: window_v1, the 30-day window as a fallback (product correctness, NOT a scored fix)

- **Status:** APPROVED as planned (user, 2026-11-17): rule 3 unchanged (`zero`, 365 days, only at `days` 30). Held-out final done first (2026-11-17, at `428b1ca`). Vectors `tests/vectors/window_fallback_vectors.json` written by hand before any code. Built `73e1b2d`; on as a phone default `3c3c75a` (`phone.py`, outside `frozen.FINAL`; user, 2026-11-17).
- **Scope:** a product correctness change for UAT and the defense (2nd week of December). It is not an accuracy-phase change: it is not scored, not compared on the dev sets, and not part of the held-out final. It must be shown not to change any dev or held-out result at the fixed evaluation dates.

## 1. The problem

- The phone searches only `now − days ≤ published ≤ now`, and the query model sends `days` 30 (the contract maximum) unless the student names a shorter period. All 57 dev query replies send 30.
- **The snapshot ages out:** every snapshot row is posted 2026-11-06 17:16 to 2026-11-07 15:34 (+08:00). From about 2026-12-06/07 every row is older than 30 days, so every live-mode search returns nothing and every question becomes "not found". That falls in the defense week.
- **Evergreen rules vanish:** dress code, uniform rules and the Good Moral process stay valid for months, but they become unsearchable 30 days after posting. This was recorded as a known limitation in `accuracy-phase.md`.

## 2. What was measured first (prototype outside the repo, no model calls)

Replayed on the frozen dev run (`strip_nf-1.json`: the saved arguments of all 57 cases, rank_v1 + and_v4):

| Variant | Dev cases changed |
|---|---|
| **fill**: `days` 30 as a preference; older rows (up to 365 days) fill the slots left after the in-window rows | **1**: taglish-09 gains ann-018 |
| **zero**: older rows are searched **only when the in-window search returns 0 results** | **0** |

- **Why "fill" is rejected:** taglish-09 ("Kailan ang examinations sa pangalawang term?") is a not-found trap. ann-018 is the *first-term* midterm schedule, 43 days old at 2026-11-02. Under "fill" the model would see a stale exam schedule next to a question about another term's exams. That is the stale-answer risk the 30-day window was quietly preventing.
- **Snapshot sweep:** every word (3+ letters) of every snapshot title, 187 words, as a query with `days` 1, 7, 14 and 30, at 2026-11-10 and 2026-11-14: **0 of 1496 searches differ under either variant.** At both instants no visible snapshot row is older than 30 days, so the fallback can never add a row there.

## 3. The rule (window_v1)

1. Run the search exactly as today (contract validation, `days`, matcher, rank_v1, limit). If it returns at least one result, return it unchanged.
2. If it returns **0 results** and `days` is **30** (no shorter period named; the contract maximum, and the value the model sends by default), search again over `now − 365 days ≤ published ≤ now` with the same query, matcher, rank, limit and excerpt rule.
3. If `days < 30`, the student named a period: no fallback (the window stays a hard filter).
4. The visibility rules (PUBLISHED, not archived, not scheduled, not in the future) are unchanged. The Spring allowlist still applies to the feed.
5. The outcome records `window_fallback: true` (numbers only in the log), as retry_v1 recorded `retry`.
- **The horizon (365 days)** is a product choice, not fitted on any eval data. It covers an academic year. Rows older than that stay unsearchable.
- **Missing `days`:** Spring's and the contract's default (7) applies first, so it counts as a shorter period: no fallback. The model never omits it in the dev runs.

## 4. Proof that no dev or held-out result can change (vectors, before any code)

1. **Structural, any question (held-out and flow13):** a test over the snapshot (skipped if the gitignored snapshot is absent) asserts that at 2026-11-10T10:00 and 2026-11-14T10:00 **no visible row is older than 30 days**. Under rule 2 the fallback can then only run when nothing is visible in the window at all, and then it finds nothing new. So window_v1 returns exactly today's results for **every** possible query and `days`. This covers the held-out questions without reading them.
2. **Sweep vectors:** the 1496-search sweep above, committed as a test against the snapshot (skipped if absent): identical results at both instants.
3. **Dev replay:** the saved arguments of all 57 dev cases (`strip_nf-1.json`), searched with window_v1 at their fixed `now`, must equal their saved results case by case. The seed's only row older than 30 days at 2026-11-02 is ann-018. The one dev case that reaches it (taglish-09) has in-window results, so the fallback never runs there.
4. **Hand-written rule vectors** (synthetic rows, `tests/vectors/window_fallback_vectors.json`), written before any code:
   - in-window results exist (no fallback, even if older rows match)
   - 0 in-window results and an older match at 31 days (found)
   - 0 in-window and a match at 366 days (not found)
   - `days` 7 with a match at 10 days (not found: a named period)
   - the fallback keeps rank_v1 order and the limit
   - a future or unpublished older row (never)
   - a match exactly at the 365-day boundary
   - the snapshot-in-December case: every row 35 days old, 0 in-window, so all of them are searchable again
5. **Parity:** Python `search_feed(..., window="window_v1")` and TS `searchRows` / `makeFeedSearch`, checked on Node and Hermes against the same vectors.

## 5. Risks (for the decision)

- **Stale answers when nothing current matches:** an old row (last term's schedule) can reach the model when no current row matches. Mitigations already in place: the list under every answer shows each row's posted date, and the label tells the student to check the announcements. Not mitigated: the model may answer from a stale row as if it were current.
- **Partial fix for evergreen rules:** an old rule is found only when no row in the window matches the query. If a recent row matches too, the old rule stays hidden. Fixing that needs "fill", which section 2 shows is unsafe on a trap.
- **Not measured on quality:** with the snapshot, the dev and held-out dates never trigger it. A quick check on the defense date (now = 2026-12-10, flow13 questions) would show the effect, but that is a demo check, not a score.

## 6. Order

1. User approves the rule (or "fill", or another horizon).
2. **The held-out final runs first, at the freeze commit, before window_v1 is built.** The final then measures exactly the frozen set, and window_v1 can't be mistaken for part of it.
3. Commit the vectors and the snapshot invariance tests, then the code (Python + TS, off by default).
4. Run the dev replay check (section 4.3) and the snapshot tests, and record them in the devlog.
5. Switch it on as a phone default through `frozen.py`'s phone settings. This is a product setting outside the FINAL eval configuration, so `--config final` stays as run. Then re-vendor the test app and re-check the flow test on the defense date.
