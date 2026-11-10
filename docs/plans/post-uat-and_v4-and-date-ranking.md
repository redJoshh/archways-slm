# Post-UAT plan: and_v4 ("pasok") and date-aware ranking

**Status:** PLAN ONLY (user, 2026-11-10). Nothing is built and nothing has been scored.
Source: the Nothing Phone 3a Pro live run (devlog, 2026-11-10), questions q11–q13.

## Rules for both changes

- **Write the rules first.** Each rule, its frozen data file and its hand-written vectors are committed before any replay or model run. After that a rule is never tuned; a change is a new version.
- **"Nothing gets worse", on every set, each change alone and then both together:**
  - The sets: e2e34, Taglish10, and the labelled flow dev set (q01–q13).
  - Replay first (saved queries, no model calls), then cold runs with qwen3:0.6b (UAT), then gemma3:1b for comparison.
  - Counts that must not get worse:
    - answerable hits
    - answerable `answer` paths
    - failed after guards
    - unsafe before and after guards
- **Traps are reported separately:** the `expects_not_found` cases and flow q10, as clean or not clean at retrieval, plus the path taken.
- **The held-out file is used only for the final comparison.**
- **Parity:**
  - A Python reference: `fakebackend.py` / `feedindex.py`.
  - A TS port: `search.ts`.
  - Vectors in `feed_vectors.json` (`export_feed_vectors.py`), run on Node and the Hermes CLI.
  - A mutation check, and a phone run before shipping.

## 1. and_v4 = and_v3 + "pasok" → class

**Rule:**

- A new frozen file, `contracts/search_synonyms_v2.json`: v1's map plus `"pasok": ["class"]`. v1 stays frozen.
- The matching is and_v3's, unchanged. A synonym is a plain substring, so `class` also covers "classes".
- Known side effect: the substring also matches "classroom" and "classification". and_v3's whole-word rule applies only to the plural alternative, not to synonyms.
- New vectors, written by hand before the code:
  - `pasok` alone
  - `pasok` with another word
  - a row with only "classes"
  - a row with "classroom" (matched, by design)
  - "pasok" as the only word of a two-word query whose other word is a stopword

**Why revisit:**

- On 2026-10-31, `pasok` was left out because it breaks taglish-08's trap, and it was to be revisited with real announcements.
- q13 (live, 2026-11-10) is that evidence. The query call wrote `pasok`, and search returned 0 results, a false `not_found`. Row 14 (start of Second Term classes) exists.

**What to report:**

- **taglish-08** ("May pasok ba sa November 16-18?", `expects_not_found`):
  - Whether retrieval stays clean. Expected not to: any seed row with "class" in the days window now matches.
  - The path the answer step then takes. **Honest:** `answer_not_found`, or an `answer` that says there is no announcement about classes on those dates. **Dishonest:** an answer presenting another row, such as ann-007's library hours on those dates, as being about classes.
  - The guard result and the e2escore failures.
- **q13:**
  - Whether row 14 is retrieved at all.
  - **Already visible, not a scored run:** the snapshot replay used to record the live run gave `class` → 34, 33, 20, 17, 16 (11 rows contain "class"). Row 14 is not among them.
  - So under newest-first with `limit` 5, the synonym alone probably still misses row 14. Only the replay will confirm it.
  - Report it as it comes out; don't add words or raise the limit to fix it.
- **Interaction with (2):** taglish-08 has a date. Score and_v4 alone, then with date ranking, because ranking ann-007 first could make the trap's answer worse.

## 2. Date-aware ranking

**Rule:**

1. **Question dates:** `e2escore.claims(question).dates`, the guard's parsing, unchanged:
   - "November 30, 2026" and "Nov. 30th"
   - "30 November" and "30th of Nov 2026"
   - "2026-11-30"
   - with the guard's space table
2. **A result matches** if `claims(title + " " + full plain text).dates` contains any question date.
   - The full text is searched, not the 500-character excerpt: the feed index holds it.
3. **Order:** among the rows that pass the matcher and the days window, matching rows come first. Each group keeps today's order: newest first, then by id.
   - **Ranking happens before the `limit` cut.** q11's row 16 was 5th of 5, and in general the right row can be outside the top 5.
4. **No question date** (or none parsed) leaves the order unchanged, so every and_v3 vector without a date must still pass.

**Limits, taken as they are from the guard's parsing and documented, not fixed in v1:**

- **Matching is on (month, day) only.** The guard pairs no year with a date, so "November 30, 2025" matches a row about November 30, 2026.
- **Ranges:** "November 16-18" yields only (11, 16).
- **Relative dates** ("bukas", "tomorrow", "next Monday") are not parsed.
- **Numeric dates** such as "11/30" are not parsed.

**The question has to reach the search.** The query prompt drops dates from `query` ("leave out ... dates"), so the ranking reads the raw question, not the arguments.

- `AssistantDeps.search(arguments)` becomes `search(arguments, { question })` in TS. Python's `flow()` passes the question the same way.
- `makeFeedSearch(index)` forwards it to `searchRows()`.
- The tool contract's arguments are unchanged.
- The schema `$comment` "newest first" becomes "date-matching rows first, then newest first" in a new contract version. Since ADR 0006 the ordering is an internal, versioned phone setting (`rank_v2`), not a Spring guarantee.

**Python/TS parity:**

- **Date parsing:** guard-ts already ports `claims()` and passes the guard vectors on Hermes.
  - Export it from `guard.ts` and import it in `search.ts`. Don't write a second copy.
  - Python `fakebackend` imports `e2escore.claims`.
- **New `rank` vectors**, written by hand before the code and exported by `export_feed_vectors.py`:
  - a dated question whose row is 6th by date
  - two matching rows (newest first between them)
  - a date only in the title
  - a date only past character 500
  - an ISO date
  - "30 Nov"
  - a range (only the first day counts)
  - a year mismatch (still matches; the documented limit)
  - no date (order unchanged)
  - a date with no matching row (order unchanged)
- **Runs:** Node and Hermes. Mutation checks on the following, each restored after:
  - the partition
  - "rank before the cut"
  - the full text against the excerpt
- **UAT log:** add `dateRanked`, the number of date-matching rows in the results (numbers only, no text).

**What to report:**

- q11: is row 16 ranked first?
- taglish-08 under the combination with (1).
- e2e cases with dates in the question. They are listed before the run, from the question texts, without looking at results.

## 3. Mobile integration note (recorded in the assistant-ts README)

- Load and prime the model in the background at app start, never on the first question.
- The Nothing Phone 3a Pro live run measured a cold load of 20,431 ms, against 1,104 ms warm, and priming of 3,697 ms.
