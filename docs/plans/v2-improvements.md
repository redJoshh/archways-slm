# Plan: v2 improvements (no training), with a new held-out protocol

- **Status:** APPROVED (user, 2026-11-17), with the decisions in section 7. They override the text above where they differ.
  - v2 held-out hash: `EE9F407AF9BD8899C1D247DCEE10330DD1D2860B13E3C6F6482C81FD5839173C` (the user, `Get-FileHash`, before any v2 fix).
- **Scope:**
  - **The rule** (ADR 0007): tools, code-level safeguards and prompt design only.
  - **Model:** qwen3:0.6b, on the device, with the same storage budget (no larger model).
  - **The v1 held-out set stays closed.**
- **Time box:** the kept v2 set is frozen by **2026-12-01**. Anything not finished by then stays out. The app is then integrated and rehearsed before the defense (2nd week of December).

## 1. v2 held-out protocol

To be recorded on approval as a new section of `accuracy-phase.md` and an ADR 0007 amendment.

- **The file:**
  - A NEW held-out file, written by the user for v2: 30 cases (24 answerable + 6 traps), the same JSONL format, outside the repo.
  - Claude Code never opens, reads or asks for it. The user runs it and pastes only the printed lines.
- **Hash first (proposed addition):** before any v2 fix is built, the user records the file's SHA-256, for example with `Get-FileHash -Algorithm SHA256 <path>`. It goes in the devlog, and both v2 runs must match it. That proves the file was fixed before the v2 changes were designed.
- **Fixed now:** 2026-11-17T10:00:00+08:00 for every v2 held-out case. `eval_heldout.py` gets a `--protocol v2` switch that sets it; v1's 2026-11-14 stays for the closed set.
- **Configurations in `eval_heldout.py`:**
  - `shipped` = `frozen.FINAL` + window_v1 (`phone.FALLBACK`), what the app ships. It is the **v2 BASELINE**.
  - `v2final` = the v2 kept set (a new frozen `FINAL_V2`, added at the v2 freeze). It is the **v2 FINAL**.
  - `baseline` and `final` stay as they are, for the record. They are refused with `--protocol v2`.
- **At most two runs** on the v2 file, both by the user, with the same manual review of the private report. Scored and human-reviewed numbers are reported side by side.
- **Before the v2 baseline:** `eval_flow.py --verify-baseline data/local/runs/baseline-1.json` must print `VERIFY OK` at the run commit, with a clean tree.
- **Order:** the v2 baseline runs **before any v2 fix is built** (as in v1), right after `shipped` is added and verified.
- **The seed ages at the v2 date. Note for the user, about the file's content:**
  - At 2026-11-17, **8 of the 22 visible seed rows are older than 30 days**: ann-002, 004, 011, 014, 016, 017, 018, 025.
  - Any v2 held-out case that relies on one of them is found only through window_v1, and only when nothing in the window matches.
  - So `shipped` and the v1 `final` can differ on seed-based cases. That is real product behaviour, not a harness change.
  - Snapshot rows (posted Nov 6–7) are all inside the window at this date.
- **No pass/fail thresholds,** as in v1. With 24 answerable cases, a difference of one or two is noise.

## 2. Rules for every v2 fix (v1's section 3 rules, plus two)

1. **Pre-registered:** the rule, its version name, any frozen data file and hand-written vectors are committed before any run. The rule is never tuned after that; a change is a new version.
2. **Parity:** the Python reference and assistant-ts change together. The vectors run on Node and the Hermes CLI, with at least one mutation check per rule.
3. **Cumulative:** each fix is tested on top of the earlier kept ones.
4. **"Nothing gets worse",** on each dev set separately (e2e34, taglish10, flow13, and the new rules set, section 3 (a)):
   - helpful doesn't fall
   - **no case loses AI-correct (case by case, new in v2)**
   - no case becomes unsafe
   - wrong AI answers don't rise
   - traps are reported per case
5. **Deterministic fixes are measured by replay first.** (a), (b), (c) and (d) act only on the saved reply, the saved results and the question. So their exact dev effect is a replay of `strip_nf-1.json` plus the new set's baseline, with no model call.
   - (e) changes the search, so it needs model runs: `--reuse-queries`, then answer calls for the changed cases.
   - (f) changes the prompt, so it needs a full cold run.
   - **Before the freeze,** one full cold dev run of the whole kept set must equal the replays' predictions.
6. **Dev only:** no v2 fix is ever scored on a held-out file before the v2 final.

## 3. Candidate fixes, in this order

### (a) contradiction_v1: block a permission reply when the source prohibits

- **Admissible only with dev evidence.**
  - The failure was first seen in the v1 held-out review, and no saved dev reply shows it: the only "Yes" reply, e2e-015, is correct.
  - **Step 0:** a new dev set `rules10` (`data/local/rules_cases.jsonl`, gitignored like flow13).
    - About 10 cases from the **snapshot only**, never from any held-out file, at now 2026-11-17T10:00+08:00.
    - About 6 permission questions whose source prohibits (expected answer "no"), and about 4 controls whose source permits or is neutral (to count false blocks).
    - Claude Code drafts the cases and the user approves the labels. The file's SHA-256 goes in the devlog before any run.
  - **Then a baseline run of `shipped` on `rules10`.**
  - **Pre-registered admissibility:** if that baseline shows **0** permission contradictions, (a) is not built (no dev evidence), and the plan moves on to (b).
- **The rule** (all three must hold; then the path is `guard_fired`-like, a new code `contradiction`, and the list is shown):
  1. **The question is a permission yes/no question.** After lowercasing it starts with or contains, as whole words: `can i`, `can we`, `can students`, `may i`, `may we`, `is it allowed`, `are we allowed`, `am i allowed`, `allowed ba`, `pwede ba`, `puwede ba`, `pwede`, `puwede`, `bawal ba`.
  2. **One of the listed results' title + plain body has a prohibition marker** (whole words, case-insensitive): `prohibited`, `not allowed`, `not permitted`, `strictly prohibited`, `strictly not allowed`, `bawal`, `forbidden`, `banned`, `must not`.
     - **Changed from the request:** "strictly" alone is dropped. It is too broad: the snapshot has "strictly limited to enrolled students", which is a restriction, not a prohibition.
  3. **The reply asserts permission:** its first word is `yes` / `oo` / `opo`, or it contains `allowed`, `permitted`, `encouraged`, `pwede`, `puwede` or `can` with no negation in the 3 words before it (`not`, `never`, `no`, `hindi`, `bawal`, `cannot`, `can't`).
- **Targets:** permission contradictions on `rules10` (and the v1 held-out failure type).
- **What could get worse:**
  - A correct "yes" is blocked when a listed result prohibits something else. Example: a uniform rule permits hoodies over Type A but bans sleeveless tops. The student still gets the list, so helpful is kept, but AI-correct can fall.
  - The `rules10` controls measure this. "No case loses AI-correct" decides.

### (b) echo_v1: a reply that only restates the question becomes answer_not_found

- **Dev evidence exists:** flow13 q08's reply restates the question and lists none of the 5 banned items (AI_NOT_CORRECT, missing 5).
- **Why plain word overlap isn't enough:** it would also block correct restate-then-answer replies (q01, q03, e2e-026 add the office or the date).
- **The rule:** the reply is an echo if both hold:
  1. it has **no date or number** (guard claims) that isn't in the question
  2. its **new content words** number at most 2: the reply's rank_v1 content-word tokens, minus the question's, with a plural `s` stripped on both sides
- **Then:** the reply is treated like the not-found sentence, so the path is `answer_not_found` and the student gets the list.
- **Targets:** q08 (AI_NOT_CORRECT → answer_not_found; helpful stays).
- **What could get worse:** a short correct answer whose fact is a name already in the question (yes/no restatements such as "Classes are suspended on November 30" for "Are classes suspended on November 30?"). AI-correct would be lost on such a case. The replay lists them before anything is kept.

### (c) past_note_v1: mark dates in the reply that are before now

- **The rule:**
  - For each full date with a year in the reply (the guard's date parser), add " (already passed)" right after the date if the date is before now's Manila day.
  - For a range, it goes after the end date, and only if the end is before today.
  - Dates without a year are left alone (ambiguous). Today is not "passed".
  - It applies after the guard and strip_nf, on the `answer` path only, and adds no digits. So scorer_v1's claims are unchanged.
- **Targets:** past-date framing (flow13 q12, "is held on August 7, 2026" at now 2026-11-10).
- **What could get worse:**
  - The past date in the reply belongs to a still-valid rule ("effective August 1, 2026"). Then "(already passed)" is true but reads as if the rule expired.
  - The replay lists every appended note for review.

### (d) extract_v1: when/what-time questions answered by quoting the source, without the model

- **The question classifier** (lowercased, whole words or phrases): `when`, `what time`, `what date`, `what day`, `until when`, `until what time`, `how long`, `kailan`, `hanggang kailan`, `anong oras`, `anong araw`, `anong petsa`, `ilang araw`.
  - If the question also contains `which`, `who`, `what office` or `ano ang` (an entity question), it is not classified.
- **Admissibility of the top result:**
  - The top rank_v1 result must contain **every** question content word (`points` covers all words) and have at least one date or time.
  - Otherwise the normal model path runs.
  - This is the safeguard for traps like taglish-09: a second-term question with a first-term schedule ranked first ("pangalawang" isn't in the row, so no extract).
- **The sentence picker:**
  - Split the top result's whole plain body (and the title as sentence 0) at `.`, `!` or `?` followed by whitespace and an uppercase letter or a digit, or at the end. A fixed abbreviation list doesn't split: `A.Y.`, `No.`, `St.`, `Dr.`, `Mr.`, `Ms.`, `Sr.`, `a.m.`, `p.m.`, `e.g.`, `i.e.`, `vs.`.
  - Keep the sentences with a date (guard parser) or a time (`\b\d{1,2}(:\d{2})?\s?(am|pm|a\.m\.|p\.m\.|nn|noon|mn)\b`, case-insensitive).
  - Pick the one with the most question content words. Ties go to the earlier sentence.
  - Cut it to 300 code points at a word boundary with "…".
- **Output:** a new path `extract`. The text is a label, the quoted sentence, a blank line, then the results list. No query change and no answer call, so it is much faster on budget phones.
- **Decisions needed (user):**
  1. **The label text.** It must not say "AI answer", because none is generated. Proposal: "From the announcement below:".
  2. **Scoring.** scorer_v1 is frozen. Proposal: score `extract` exactly as an `answer` (same text rules, so it counts in helpful, AI correct and unsafe). Report it separately as "extract correct", with the metric renamed "answer correct (AI + extract)" in v2 reports.
- **Targets:**
  - when-questions where the model said not found although the source was listed (dev: e2e-001, e2e-005, e2e-029, taglish-01, q09 are candidates; the replay decides)
  - past-date framing on when-questions (the quote keeps the source's tense)
- **What could get worse:**
  - The quoted sentence is the wrong date in a correct row (a row with several dates), which is unsafe.
  - A correct model answer is replaced by a less specific quote, which loses AI-correct.
  - Both are visible in the replay case by case.

### (e) Taglish lexicon v1: synonym file v3 and matcher and_v5

- **The lexicon:** `contracts/search_synonyms_v3.json` = v2 plus about 50–100 Taglish/Filipino → English campus terms. Examples: `klase`→class, `pasok`→class, `bayad`→payment, `pagsusulit`→exam, `pasukan`→class opening, `bakasyon`→break, `aklatan`→library, `uniporme`→uniform, `kailangan`→required.
  - **From general language knowledge only.** Never from any held-out file. **Written and committed before any run, and before re-reading the dev Taglish cases.**
- **Matcher and_v5** = and_v3's rules with v3 synonyms. The format is unchanged, so rank_v1 points use it too.
- **Entry rules:**
  - Keys are 4+ letters, lowercase, one word.
  - Alternatives are English words already used by the matcher's substring rule.
  - No key may be a substring of a common English word: checked against a word list in a test.
- **Dev contamination note:** some terms will appear in taglish10/flow13 questions (q13 "pasok" already does). The report splits the dev effect into "terms that appear in dev questions" and "the rest". The held-out v2 run is the real test.
- **Targets:** taglish-04 (query `kailan sinusus`, 0 results) and Taglish queries the model passes through untranslated.
- **What could get worse:** more unrelated lists on traps (a broader match), and a different rank order. Measured by the retrieval replay (traps' results, source places) before any model run.

### (f) answer prompt v5: v1's exact wording with the compact result format only

- **The prompt:** `prompts/e2e_answer_v5.txt` = v1's text byte for byte (a new file for versioning). Only the results message changes, to a compact block.
- **Format conflict (decided here, for approval):** v2's compact message assumed newest-first order (it raises otherwise) and dropped the `posted_at` name. Neither holds now: rank_v1 orders by relevance, and v1's rules say "posted_at". So v5's block is, in rank order:
  ```
  N. <title>
  office: <office> | posted_at: YYYY-MM-DD[ | year_level: Y]
  <excerpt, whitespace collapsed, < escaped>
  ```
  That keeps every v1 sentence true. `id` and `priority` are dropped, as in v2.
- **Targets:** isolating the format's effect (v2 mixed format and wording). Also fewer case tokens, which means fewer budget fallbacks on phones. That benefit isn't in the dev score, which runs with the budget off, so case-token counts are reported (they are deterministic).
- **What could get worse:** like answer v4 (−7 AI-correct), any prompt-side change can move many answers. "No case loses AI-correct" will likely decide it.

## 4. Schedule (time box 2026-12-01)

| Dates | Step |
|---|---|
| 11-17 | Plan approval. The user records the v2 file's SHA-256. |
| 11-18 | Protocol recorded (accuracy plan, ADR 0007). `shipped` config + `--protocol v2` + tests. VERIFY OK. **User runs the v2 baseline.** |
| 11-18–19 | `rules10` drafted, labels approved, hash recorded. Baseline on `rules10`. Admissibility of (a). |
| 11-19–20 | (a) pre-registered, built, replay |
| 11-20 | (b) pre-registered, built, replay |
| 11-21 | (c) pre-registered, built, replay |
| 11-22–24 | (d) pre-registered (classifier, picker, label and scoring decisions), built, replay |
| 11-25–26 | (e) lexicon frozen first, then built: retrieval replay, then model runs on the changed cases |
| 11-27–28 | (f) pre-registered, built, full cold run |
| 11-29 | The full cold dev run of the kept set (it must match the replays). Freeze `FINAL_V2`. |
| 11-30 | **The user runs the v2 final** and reviews it. |
| 12-01 | Recorded. Re-vendor, integration guide amendment (configuration and `VENDORED.md` hash). Then integration. |

If a step slips, the later fixes are dropped in order: (f), then (e), then (d). (a)–(c) are small and deterministic.

## 5. Effects on the app (if kept)

- **(a), (b), (c):** post-processing of the reply in `assistant.py` / `flow.ts`, new path codes in the UAT log. No new model calls.
- **(d):** a new path and a new label text. It is faster on budget phones (no answer call).
- **(e):** a new matcher default (`PHONE_MATCHER` from `FINAL_V2`).
- **(f):** a new answer prompt. The session-file names change automatically (the prompt's SHA-256).
- **The integration guide** gets an amendment with the `FINAL_V2` values and the new vendor hash. Its milestones are unchanged.

## 6. Open decisions for approval

1. The whole plan, including adding the v2 file's hash before any fix.
2. (a): the permission-question trigger, dropping "strictly" alone, the `rules10` set (Claude Code drafts, the user labels), and the 0-evidence stop.
3. (d): the label text, and scoring `extract` as an answer under scorer_v1.
4. (f): the compact block with `posted_at`, in rank order.
5. The drop order if time runs out: (f), (e), (d).

## 7. Decisions (user, 2026-11-17), folded in

1. **Approved,** including the hash first. The hash is above; `eval_heldout.py` checks it as `V2_SHA256`.
2. **(a):** permission-type yes/no questions only, with "strictly" dropped. If `shipped` shows no contradiction on `rules10`, (a) is not built. Claude Code drafts `rules10` from the snapshot, and the user labels it before any run.
3. **(d):** the label is "From the announcement below:" (never "AI answer"). The quote path is scored as an answer and reported separately as "extract correct".
4. **(f):** the compact format as proposed (`posted_at` label, rank order).
5. **New order: a → b → c → e → d → f,** so that (d)'s "every content word" check can use the Taglish lexicon from (e). If time runs short, drop **(f) first, then (d); keep (e)**. The schedule in section 4 is reordered to match: (e) on 11-22–23, (d) on 11-24–26.
6. **(c) also marks past dates inside (d)'s quotes.**

### Implementation notes (2026-11-17)

- **Config to protocol, not `--protocol`:** each config belongs to one protocol (`baseline`, `final`: v1 at 11-14; `shipped`: v2 at 11-17).
  - So the date can't be mixed up, and no switch is needed.
  - A v2 config refuses any file but the recorded hash, and a v1 config refuses the v2 file, before any model call.
- **Correction to section 1:** held-out files are over the **snapshot only** (`eval_heldout.py`'s format; source ids are checked against the snapshot). So the seed-age note doesn't apply to the held-out file.
  - At 2026-11-17 every snapshot row (posted Nov 6–7) is inside the 30-day window.
  - So window_v1 can't change any v2 held-out result at its fixed date, and `shipped` searches exactly like `final` there.
  - The note stays true for dev cases on the seed at later dates.

## 2026-11-18: contradiction_v1 rule, pre-registered (fix (a); user: build exactly as registered)

The rule of section 3 (a), with the details the plan left open written out. These details were written **after** the `rules10` baseline run. They are the reading the devlog's prediction used, and they change nothing it predicted (r04 and r02 blocked, nothing on the v1 dev sets). No threshold or word list is changed.

- **Where it applies:**
  - only when the flow would show the `answer` path (the guard passed the reply, and the list can be built), on the guard-passed reply text
  - **if it fires:** path `guard_fired`, code `contradiction`, text = the results list
  - **off:** nothing changes
- **Tokens:** lowercase, then maximal runs of and_v3 word characters (`is_word_char`, the generated `WORD_RANGES`).
  - An apostrophe (U+0027 or U+2019) between two word characters belongs to the token, and U+2019 is written as U+0027. So `can't` and `can’t` are one token, `can't`.
  - A phrase matches when its tokens appear consecutively (whole words).
- **1. Question trigger:** any phrase of `can i`, `can we`, `can students`, `may i`, `may we`, `is it allowed`, `are we allowed`, `am i allowed`, `allowed ba`, `pwede ba`, `puwede ba`, `pwede`, `puwede`, `bawal ba` in the question's tokens.
- **2. Source marker:** any phrase of `prohibited`, `not allowed`, `not permitted`, `strictly prohibited`, `strictly not allowed`, `bawal`, `forbidden`, `banned`, `must not` in the tokens of `title + "\n" + excerpt` of **any** listed result.
  - That is the contract fields the model and the student see. The flow has no other body text.
- **3. Reply asserts permission:**
  - **either** its first token is `yes`, `oo` or `opo`
  - **or** a token `allowed`, `permitted`, `encouraged`, `pwede`, `puwede` or `can` has none of `not`, `never`, `no`, `hindi`, `bawal`, `cannot`, `can't` among the (up to) 3 tokens before it
- **It fires when 1, 2 and 3 all hold.**
- **Recorded with the decision (user, 2026-11-18):**
  - **Evidence:** `shipped` produced a real contradiction on `rules10` (r04), which (a) blocks.
  - **Known false block:** r02, a person-correct Taglish answer that restates "Pwede…?" and then states the prohibition. By human judgment one correct AI answer is lost. The student still sees the list with the source; the scorer doesn't see the loss.
  - **Likely Taglish bias:** answers that echo a Taglish permission question ("pwede") are more likely to be falsely blocked.
  - **Reach:** only snapshot rows 19 and 29 use (a)'s prohibition words.
  - **Any refinement** (for example ignoring permission words that appear in the question) is a separately pre-registered contradiction_v2 **after the v2 final**, not in this phase.
- **Vectors:** `tests/vectors/contradiction_vectors.json`, hand-written before any code.
- **Result (2026-11-18): KEPT** (devlog). rules10: helpful 6 → 7, wrong answers 2 → 1; v1 dev sets unchanged. r02 is the recorded human-judged loss.

## 2026-11-18: echo_v1 rule, pre-registered (fix (b), on top of contradiction_v1)

The rule of section 3 (b), made exact with rank_v1's own definitions, so that nothing new is invented. Written before any echo_v1 code or run.

- **Where it applies:**
  - only when the flow would show the `answer` path: the guard passed the reply, the list can be built, and contradiction_v1 didn't fire
  - on the guard-passed reply text
  - **if it fires:** path `answer_not_found`, code `echo`, text = the results list
  - **off:** nothing changes
- **Terms:** `rank.question_terms(text)` (Python) / `questionTerms(text)` (TS), applied to the question and to the reply alike:
  - content words: the lowercased text with parsed dates blanked; tokens with a digit or of one code point dropped; `AND_V2_STOPWORDS` and `rank_stopwords_v1` dropped; first occurrence kept
  - dates, and numbers (a date's year is a number, its day is not)
- **Plural:** each content word is replaced by the matcher's `plural_alternative(word)` (`pluralAlternative`) when that is not null. So `items` → `item`, `includes` → `include`; `included` is unchanged.
- **It fires when both hold:**
  1. the reply's dates are a subset of the question's dates, and the reply's numbers a subset of the question's numbers
  2. the number of distinct normalised reply words that are not normalised question words is **at most 2**
- **Recorded risks (from the plan; vectors E4, E6, E8 pin them):**
  - a short correct answer whose new content is 1–2 words (a two-word office name, or a bare "Yes.") counts as an echo
  - a yes/no restatement that adds nothing new counts as an echo
  - The keep rule ("no case loses AI-correct") decides.
- **Vectors:** `tests/vectors/echo_vectors.json`, hand-written before any code (E14 added after the code to close a mutation gap; rule unchanged).
- **Result (2026-11-18): KEPT** (devlog). flow13 q08 → answer_not_found; nothing else changed on any dev set.

## 2026-11-18: past_date_v1 rule, pre-registered (fix (c), on top of (a) and (b))

The name is **past_date_v1** (the plan's "past_note_v1"). The user pinned the points marked (user); the rest makes them exact. Written before any past_date_v1 code or run.

- **Scope (user):**
  - only the AI-answer text: the guard-passed reply on the `answer` path, after contradiction_v1 and echo_v1
  - and (d)'s quotes, when (d) is built
  - **never** the results list or any other path
  - If at least one note is added, the outcome gets code `past_date`; the path stays `answer`.
- **Date spans:** exactly the spans the guard and scorer parse.
  - Python `e2escore.date_scan(text)`, TS guard-ts `claimsAndRest(text).spans`: the same patterns, order and blanking. Neither frozen module is edited.
  - Spans are sorted by start. Offsets are code points (Python) or UTF-16 units (TS) of the same text; every match is ASCII.
- **A span's year:**
  - for `YYYY-MM-DD`, its first four digits
  - otherwise, the four-digit run that ends the span text, if any (a day has at most 2 digits, so a trailing 4-digit run is the year)
  - otherwise none
- **Year-less dates (user):** annotated only if they resolve to a full date in the cited source.
  - **Cited source:** for an AI answer, every listed result; for a (d) quote, the quoted row.
  - Each source text is `title + "\n" + excerpt`.
  - Collect the years of the source spans with a year and the same (month, day). If there is **exactly one** distinct year, use it. Otherwise (none, or several) leave the date.
- **Ranges (user: judged by the end date, the note after the whole range):**
  - Two consecutive spans A, B form a range when the text between A's end and B's start, with ASCII whitespace stripped and lowercased, is exactly one of `to`, `until`, `through`, `thru`, `-`, `–` (U+2013), `—` (U+2014).
  - A is then not judged alone. The range is judged by B (its year, or B resolved as above), and the note goes after B.
  - No chaining: the scan continues after B.
  - Recorded limit: a day-only end ("June 5 to 7, 2026") is not a parsed date, so it is not a range. "June 5" is then judged alone, and without a resolvable year it is left.
- **Past (user):** the calendar date (year, month, day) is **strictly before** now's date in Manila (UTC+08:00). The same day is not past. An impossible date (for example February 30) is left.
- **The note (user):**
  - The text ` (already passed)` (a space, then the words) is inserted right after the span's end, or after B for a range.
  - The span includes the year when it has one, so the note follows the complete date.
  - Insertions go from last to first, so the offsets stay valid.
- **Invariance (user):** for every vector, the guard and scorer read the annotated text the same way as the original:
  - `claims(annotated) == claims(original)` (Python `e2escore.claims`, TS guard-ts `claims`)
  - the guard's `fired` and `codes` are equal on both texts, with the vector's results
  - The note has no digit and no month name.
- **Measurement (user):**
  - The scorer can't measure tense. The targeted benefit (dev: flow13 q12, and q07 if it reaches the answer path) is judged by the user's review.
  - "Nothing gets worse" applies to the scored metrics as usual.
- **Vectors:** `tests/vectors/past_date_vectors.json`, hand-written before any code (P21–P22 added after the code to close a mutation gap; rule unchanged).
- **Result (2026-11-18): KEPT** (devlog). Only flow13 q12 changes; the user reviewed it ("correct and clear").

## 2026-11-18: taglish_lexicon_v1 rule, pre-registered (fix (e): synonym file v3, matcher and_v5)

Written before the checks were run and before any dev run.

- **Candidates:** `contracts/taglish_lexicon_candidates_v1.json`, 119 Taglish/Filipino → English campus terms.
  - Written by Claude Code from general language knowledge only.
  - No dev Taglish case, held-out file or report, and no snapshot text was consulted to write them.
  - Their order is the keep order (C8).
- **The English word list:** dwyl `english-words` `words_alpha.txt` (370,105 words, public domain, Unlicense), `data/local/wordlists/words_alpha.txt` (gitignored), SHA-256 `3ed0c94610d8bcf7c11bbb49c56aa49c7234d32b66824df91f554169e572da48`.
  - It is broad rather than "common", so it errs towards dropping terms.
- **The corpus** for the collision checks: the title and plain body of every snapshot row and every seed row, lowercased. Tokens are maximal runs of letters (`str.isalpha`).
- **Checks, in order** (the user: "an English word list AND the snapshot vocabulary"; drop expansions that match unrelated announcements; drop months and common English words):
  - **C1 (key shape):** the key is `^[a-z]{4,}$` (one lowercase word of at least 4 ASCII letters).
  - **C2 (English and months):**
    - the key is not in the English word list
    - it is not a month name: English `january`…`december`; Filipino `enero`, `pebrero`, `marso`, `abril`, `mayo`, `hunyo`, `hulyo`, `agosto`, `setyembre`, `oktubre`, `nobyembre`, `disyembre`; and `may` (the "may" problem)
  - **C3 (no overlap):** the key is not already a key of `search_synonyms_v2.json`, and not in `AND_V2_STOPWORDS`, the map's `extra_stopwords` or `rank_stopwords_v1`.
  - **C4 (key collision):** in the corpus, the key never occurs inside a longer token. Every token containing it is the key itself; the matcher matches the query word as a substring, so "tren" inside "strength" is dropped.
  - **C5 (expansion collision):** each expansion has at least 4 non-space characters.
    - Every substring occurrence in the corpus must start at a token start.
    - It must be followed only by one of the suffixes `""`, `s`, `es`, `d`, `ed`, `ing`, `er`, `ers` before the token ends. A multi-word expansion is checked at its first and last token.
    - An expansion that fails is removed ("dress" in "address", "form" in "information").
  - **C6 (generic expansion):** an expansion found (the matcher's substring test on the lowercased title or body) in more than 25% of snapshot rows (more than 13 of 53) is removed.
  - **C7:** a term with no expansion left is dropped.
  - **C8 (size):** the survivors keep candidate order, and at most the first 100 are kept. If fewer than 50 survive, (e) stops and is reported; no new candidates are added after the checks.
- **Scope (decided before any run):** the expansions apply to **both** the matcher's query groups **and** rank_v1's question-overlap scoring.
  - rank_v1 is pre-registered as "a word is found by the matcher's test for a one-word query", using the active matcher's synonym map (as and_v4 did). So with and_v5 the Taglish words of the **question** are also found through their English expansions.
  - The alternative, matcher-only, would need a new rank version, which isn't in this plan.
- **The frozen files:**
  - `contracts/search_synonyms_v3.json` = v2's map + the survivors, with v2's `extra_stopwords`. Its SHA-256 goes in the devlog.
  - Matcher **and_v5** = and_v3's rules with the v3 map. It is generated into assistant-ts (`SYNONYMS_V3`) like v2.
- **Vectors:** `tests/vectors/and_v5_vectors.json`, hand-written after the checks and before any dev run.
- **Measured:**
  - first the retrieval replay (traps' results and the source rows' places)
  - then the dev runs with `--reuse-queries` (the query prompt is unchanged), cumulative on (a)+(b)+(c)
  - "nothing gets worse" on every dev set; any term that occurs in a dev question is reported separately ("dev contamination note", section 3 (e))
- **Result (2026-11-18): KEPT ON** in the v2 kept set (user decision; devlog).
  - It passes "nothing gets worse" with zero dev effect. That is because no dev question or query contains any of its 98 terms: a **dev-coverage gap, not evidence of no effect**.
  - It only adds alternatives for non-English terms that passed every collision check (C1–C8).
  - Keeping (e) was decided at plan approval (section 7.5, "drop (f), then (d); keep (e)"), **before** the v2 baseline ran.
  - The v2 final measures the kept set as a whole, so the lexicon's individual effect **can't be isolated or claimed**.
  - Unlike excerpt_v2_centred (v1), which was inert by design and stays off.

## 2026-11-18: extract_v1 rule, pre-registered (fix (d), on top of (a), (b), (c) and (e))

The rule of section 3 (d), with the user's decisions (section 7.3, 7.5, 7.6), written out exactly. Written before any extract_v1 code, before any (d) vector run, and before looking at which dev cases it would reach. Nothing here is fitted to a dev case.

- **Where it applies:**
  - in the flow, right after a valid search with at least one result, **before** the token count, the budget and the answer call
  - **if it fires:** a new path `extract`. No answer call is made (Python: the scripted answer reply and case tokens are ignored; TS: no count or answer step). `budget` is None, `result_count` is the result count.
  - **if it doesn't:** the normal path (budget, answer call, guard, (a), (b), (c)), unchanged
  - **off:** nothing changes
- **Text the rule reads (a deviation from section 3's wording, forced by the flow):** the flow, the phone and Spring results only carry the contract fields. So "the top result's whole plain body" is its **`title` and `excerpt`** (the excerpt is the body's first 500 code points), the same text (a) reads. The top result is `results[0]` (rank_v1's order in every v2 config).
- **1. Classifier.** Question tokens: `rank.tokens(question.lower())` (runs of and_v3 word characters). A phrase matches when its tokens appear consecutively.
  - **Time phrases:** `when`, `what time`, `what date`, `what day`, `until when`, `until what time`, `how long`, `kailan`, `hanggang kailan`, `anong oras`, `anong araw`, `anong petsa`, `ilang araw`.
  - **Entity phrases:** `which`, `who`, `what office`, `ano ang`.
  - **Classified** when at least one time phrase matches and no entity phrase matches.
  - Whole tokens only: `whenever`, `what times`, `what days` don't match.
- **2. The question's terms for (d):** `rank.question_terms(question)` (rank_v1's content words, dates and numbers), with every token of every **matched** time phrase removed from the content words. Dates and numbers are kept.
  - **Recorded consequence:** every other content word must be in the row, including verbs and fillers that rank_v1 doesn't drop ("does", "magbubukas", "it" as a substring). This makes (d) fire less often; the normal path runs instead. No stopword is added here.
- **3. Admissible top result.** Both must hold:
  - the reduced terms have **at least one content word** (a question that is only a time phrase, like "When is it?" reduced to nothing, is not extracted; "it" stays a word)
  - `rank.points(reduced, title.lower(), excerpt.lower(), SYNONYMS_V3) == reduced.possible`: **every** reduced content word and every date or number anchor is found in `results[0]` by the matcher's one-word test, **always with the v3 map** (the Taglish lexicon (e), as the user ordered), whatever matcher ran the search
- **4. Sentences** of `results[0]`:
  - **sentence 0** is the title, stripped of ASCII whitespace (never split)
  - the excerpt is split into lines at every run of `\n` / `\r`; each line is split after a `.`, `!` or `?` that is followed by one or more ASCII whitespace characters and then an ASCII uppercase letter or digit
  - **no split** after a period that ends one of `A.Y.`, `No.`, `St.`, `Dr.`, `Mr.`, `Ms.`, `Sr.`, `a.m.`, `p.m.`, `e.g.`, `i.e.`, `vs.` (compared case-insensitively), when the character before the abbreviation is not an ASCII letter (or there is none)
  - each sentence is stripped of ASCII whitespace; empty ones are dropped; order is kept
  - **a cut excerpt:** if the excerpt is exactly 500 code points long (`EXCERPT_CHARS`), its last sentence is dropped, because it may be cut mid-sentence
- **5. Candidates:** sentences with a **date** (any `e2escore.date_scan` span) or a **time**: `(?<![0-9])[0-9]{1,2}(?::[0-9]{2})?[ ]?(?:a\.m\.|p\.m\.|am|pm|nn|noon|mn)(?![a-z0-9])`, case-insensitive, ASCII, on the sentence with the guard's space table applied.
  - Correction to section 3: its time pattern ended in `\b`, which can't follow `a.m.`'s final period before a space, so "8 a.m. " would not match. The lookahead fixes that; nothing else changes.
- **6. Pick:** the candidate with the most `rank.points(reduced, sentence.lower(), "", SYNONYMS_V3)`; ties go to the earlier sentence (the title first). No candidate: not extracted.
- **7. Cut to 300 code points:** a picked sentence of at most 300 code points is the quote as is. A longer one is cut at the last ASCII space at index ≤ 299 that is **not inside** a date span or time match of the sentence; the quote is the text before it, right-stripped, plus `…` (U+2026). No such space, or no date or time left in the cut text: not extracted.
- **8. Guard:** `guard(quote, results, question, [])` (the same guard as the answer path). If it fires (for example a non-ASCII digit copied from the source), not extracted: the normal path runs.
- **9. Past dates ((c), user 7.6):** with past_date_v1 on, `annotate(quote, [results[0]'s title + "\n" + excerpt], now)` (the quoted row is the cited source). If a note is added, the code `past_date` is added.
- **Output:** path `extract`, text = `From the announcement below:` + `\n` + the (noted) quote + `\n\n` + the results list (`RESULTS_HEADER` and the same lines as every other path). Codes: `past_date` or none.
  - The quote has **no added quote marks**. The label is never "AI answer" (user 7.3).
  - Interaction: (a) contradiction_v1 and (b) echo_v1 apply to the model's answer only, so never to an extract.
- **Scoring (user 7.3; scorer_v1 stays frozen):**
  - `eval_flow.py` scores an `extract` outcome **exactly as an `answer`**: it hands scorer_v1 the path `answer` and the text with the extract label replaced by the answer label, so the quote is "the AI answer" for every scorer_v1 rule (must_include, must_not_include, wrong claims, unsupported, wrong row, stale, entity; a trap's extract is never correct and not clean).
  - The saved outcome keeps the path `extract`. Reports add **"extract correct"** (correct cases on the `extract` path) and name the combined metric **"answer correct (AI + extract)"**. The keep rule is the usual "nothing gets worse" on that combined metric, case by case.
- **Replay (rule 5):** (d) needs no model call. `--post-replay` re-runs every saved case of `strip_nf-1.json` and `rules10-shipped.json` through the flow with the kept set ((a), (b), (c), and_v5) and `--extract extract_v1`. A case that extracts doesn't use its saved answer reply.
- **Recorded risks (section 3):**
  - the quote is the wrong date of a several-date row (unsafe, and visible in the replay)
  - a correct AI answer replaced by a less specific quote (loses answer-correct)
  - the verb/filler consequence above (fewer extracts, no harm)
- **Vectors:** `tests/vectors/extract_vectors.json`, hand-written before any code: the classifier, the reduced words, the sentences, the pick, the cut, the guard, the past-date note, and the full flow text.
