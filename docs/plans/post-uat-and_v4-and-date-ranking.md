# Post-UAT plan: and_v4 ("pasok") and question-overlap ranking (rank_v1), shared with the answerability gate

> **2026-11-14:** superseded for order and metrics by [`accuracy-phase.md`](accuracy-phase.md); accuracy-phase.md reuses the rule texts here.

**Status:** PLAN ONLY (user, 2026-11-10). Nothing is built and nothing has been scored.

- Source: the Nothing Phone 3a Pro live run (devlog, 2026-11-10), questions q11–q13, and the q01 check.
- **Revised 2026-11-10 (user):** the date-only ranking is generalised to an overlap score over the raw question.
  - The answerability gate in `post-uat-answerability-and-excerpts.md` (a) reuses the same score: one mechanism, not two.

## Rules for every change here

- **Write the rules first.** Each rule, its frozen data files and its hand-written vectors are committed before any replay or model run. After that a rule is never tuned; a change is a new version.
- **Sets and runs:** e2e34, Taglish10, and the labelled flow dev set (q01–q13).
  - Replay first (saved queries, no model calls), then cold runs with qwen3:0.6b (UAT), then gemma3:1b for comparison.
- **"Nothing gets worse".** Counts that must not get worse:
  - answerable hits
  - answerable `answer` paths
  - failed after guards
  - unsafe before and after guards
- **Traps are reported separately:** the `expects_not_found` cases and flow q10, as clean or not clean at retrieval, plus the path taken.
- **Arms:**
  1. rank_v1 over and_v3
  2. and_v4 alone (newest-first order)
  3. and_v4 + rank_v1
  4. the gate on top of whichever of 1–3 is kept
- **The held-out file is used only for the final comparison.**
- **Parity:**
  - A Python reference: `fakebackend.py` / `feedindex.py`.
  - A TS port: `search.ts`.
  - Vectors in `feed_vectors.json` (`export_feed_vectors.py`), run on Node and the Hermes CLI.
  - Mutation checks, and a phone run before shipping.

## 1. and_v4 = and_v3 + "pasok" → class

**Rule:**

- A new frozen file, `contracts/search_synonyms_v2.json`: v1's map plus `"pasok": ["class"]`. v1 stays frozen.
- The matching is and_v3's, unchanged. A synonym is a plain substring, so `class` also covers "classes".
- Known side effect: the substring also matches "classroom" and "classification".
- New vectors, written by hand before the code:
  - `pasok` alone
  - `pasok` with another word
  - a row with only "classes"
  - a row with "classroom" (matched, by design)

**Why revisit:**

- On 2026-10-31, `pasok` was left out because it breaks taglish-08's trap, and it was to be revisited with real announcements.
- q13 (live) is that evidence: the query was `pasok`, with 0 results, a false `not_found`. Row 14 exists.

**What to report:**

- **taglish-08** ("May pasok ba sa November 16-18?", `expects_not_found`):
  - Whether retrieval stays clean. Expected not to.
  - Whether the answer step then stays honest. **Honest:** `answer_not_found`, or an `answer` saying there is no announcement about classes on those dates. **Dishonest:** presenting another row, such as ann-007's library hours on those dates, as being about classes.
  - The guard result and the e2escore failures.
  - Reported for and_v4 alone and combined with rank_v1. The date anchor (11, 16) could rank ann-007 first.
- **q13:** and_v4 alone probably still misses row 14.
  - In the recording replay, `class` matched 11 snapshot rows and row 14 was 7th newest.
  - Only rank_v1 over the full match set can lift it (see 2).
  - This is an observation, not a score.

## 2. rank_v1: rank every matched row by overlap with the raw question, before the cut

**Why** (observed on the snapshot while recording; not scored): in each case below the right row matched the query, but newest-first put it outside the 5 results.

| Question | Query | Matched rows | Right row's place, newest first |
|---|---|---|---|
| q01 | `office` | 17 | Row 18 ("offices") 10th |
| q11 | `class` | 11 | Row 16 5th (kept, but last) |
| q13, with and_v4 | `class` | 11 | Row 14 7th |

**Rule** (frozen before any run):

1. **Candidates:** every row that passes the matcher (and_v3 or and_v4) and the days window. There is no cut yet.
2. **Anchors from the raw question:** `claims(question)`, the guard's parser (`e2escore.claims` / guard-ts `claims`), unchanged.
   - **Date anchors:** each parsed (month, day).
   - **Number anchors:** each parsed number (years included). Day numbers inside a parsed date are not counted again.
3. **Content words from the raw question:**
   - Blank the parsed date spans first, as `claims()` does.
   - Split with and_v3's tokenizer (`WORD_RANGES`) and lowercase.
   - Drop tokens with a digit.
   - Drop stopwords: the matcher's stopwords plus a new frozen `contracts/rank_stopwords_v1.json`. It is written before any run and holds two lists:
     - Filipino function words: `ang, ng, sa, ba, na, mga, ano, kailan, saan, sino, may, para, po, ko, ako, namin, natin, yung, at, kung, pag, ay`.
     - Domain words that every row shares: `announcement, announcements, ust, university, santo, tomas, official`.
     - Never edited after the first run; a change is v2.
   - Duplicates count once.
4. **Found, per row** (title + " " + full plain text; the feed index has the full text, not just the excerpt):
   - **A content word** is found by the matcher's own per-word test: and_v3 substring or plural alternative, and the matcher version's synonyms. So "office" finds "offices" and, under and_v4, "pasok" finds "class".
   - **A date anchor** is found if (month, day) is in `claims(row text).dates`.
   - **A number anchor** is found if it is among the row's parsed numbers or the day numbers of its dates (`merged_claims` semantics).
   - Row claims are computed once at index time and kept on the index row.
5. **Score, in integers** (for exact Python/JS parity; the denominator is the same for every row of one question):
   - `points = words_found + 3 × anchors_found`
   - `possible = n_words + 3 × n_anchors`
   - The weight 3 is fixed now and never tuned.
6. **Order:** points descending, then today's order (newest first, then id). Then cut to `limit`.
   - With `possible = 0` (only stopwords), every row scores 0, so the order is exactly today's.
7. **The answerability gate (shared):** the gate passes if the top result's `points × q ≥ p × possible`, for a rational θ = p/q. Otherwise there is a new path, `not_about`, with no answer call: a header and then the results list. The strings come from the generator, and the path needs an ADR 0004 amendment.
   - **This replaces the separate coverage/anchor rule in the excerpts plan's (a).**
   - θ is the one fitted number. It is fitted on the e2e34 and Taglish10 replays only, as the largest θ that loses no answerable `answer` path. The flow set is a read-out.
   - θ is frozen before any cold run.

**Contract:**

- The arguments are unchanged.
- `AssistantDeps.search(arguments)` becomes `search(arguments, { question })` in TS, and Python's `flow()` passes the question too. The query prompt drops dates and words, so the score must read the raw question.
- The schema `$comment` "newest first" becomes "rank_v1 points, then newest first" in a new contract version. Since ADR 0006 this is an internal, versioned phone setting, not a Spring guarantee.

**Python/TS parity:**

- Export guard-ts's `claims()` and import it in `search.ts`, with no second copy. Python imports `e2escore.claims`.
- Reuse the stopword sets from `searchData.ts`, generated by `export_search_ts.py`, which also writes `rank_stopwords_v1`.
- **`rank` vectors**, written by hand before the code:
  - a row 10th by date that ranks 1st
  - a points tie broken by newest
  - a date found only past character 500
  - a date only in the title
  - ISO and "30 Nov" dates
  - a range (first day only)
  - a year mismatch (month and day still found)
  - a number anchor
  - a question that is all stopwords (order unchanged)
  - Taglish function words dropped
  - a plural found ("offices")
  - a synonym found under and_v4 only
  - the gate's `p/q` boundary, on and just under it
- **Mutation checks,** each restored after:
  - ranking after the cut
  - the excerpt in place of the full text
  - weight 1 in place of 3
  - the tie-breaker reversed
  - the gate's `≥` changed to `>`
- **UAT log:** add `rank: {points, possible}` for the top result, and the gate decision (numbers only, no text).

**Cost:** scoring runs over every matched row, not 5. Row claims are cached at index time, so per question it is one tokenisation of the question and set lookups. The index time on the phone is reported (it was 22 ms for 53 rows before).

**Known limits (documented, not fixed in v1):**

- **Dates are matched on month and day only:** "November 30, 2025" finds a row about November 30, 2026.
- **"November 16-18" anchors only the 16th.**
- **No relative dates** ("bukas", "tomorrow").
- **No numeric dates** such as "11/30".
- **Generic words** (for example "office", "published") still count as content words. Only the frozen list removes words.

**What to report:**

- Per arm, where the flow labels end up: q01 row 18, q11 row 16, q13 row 14 (and_v4 arms only).
- taglish-08 under each arm.
- The e2e cases with dates in the question, listed from the question texts before the run, without looking at results.

## 3. Mobile integration note (recorded in the assistant-ts README)

- Load and prime the model in the background at app start, never on the first question.
- Measured on the Nothing Phone 3a Pro live run: a cold load of 20,431 ms, against 1,104 ms warm.
