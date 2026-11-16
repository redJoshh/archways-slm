# Accuracy phase (before UAT): metrics, real-data harness, held-out protocol, improvement order

**Status:** APPROVED (user, 2026-11-14), with the decisions at the end folded in.
Section 0 (the metrics) and section 2 (the held-out protocol) are **FROZEN as of 2026-11-14**, before any harness code or run: a change is a new, dated section at the end of this file, never an edit.

**Constraint (panel commitment):** no training or fine-tuning. Only tools, code-level safeguards and prompt design.
qwen3:0.6b only. Search stays on the phone (ADR 0006). No backend change.

**Relation to earlier plans:**

- This phase moves work planned as post-UAT to before UAT. It reuses rule texts from
  `post-uat-and_v4-and-date-ranking.md` (and_v4, rank_v1, the shared gate) and
  `post-uat-answerability-and-excerpts.md` (the centred excerpt).
- Where they differ, this plan wins:
  - **Order:** cumulative a → f (section 3), not the separate arms.
  - **Model:** no gemma3:1b comparison.
  - **Metrics:** section 0, not the old count list.
- After approval, each earlier plan gets a one-line "superseded by accuracy-phase.md for order and metrics" note at its top. No other edit.

---

## 0. Metrics (FROZEN 2026-11-14)

### Definitions, per case

The harness splits the final text into the parts the student sees:

- **AI answer:** the text between `ANSWER_LABEL` and the results list, on the `answer` path only. Every other path has no AI answer.
- **Shown list:** the result ids in the results list (paths `answer`, `answer_not_found`, `guard_fired`, `answer_error`, and `not_about` once (d) exists). `not_found` shows no list.

**Wrong AI answer** (scorer_v1): an AI answer with any of:

1. a `must_not_include` phrase
2. a `wrong_claims` phrase (misattribution)
3. a date or number not supported by the results or the question (`e2escore.unsupported_claims`)
4. a date or number found only in a retrieved row that is not a source row (`wrong_row_claims`, with the case's source rows as the right rows; on a trap every retrieved row is a wrong row)
5. a stale date (`stale_problems`, cases with `superseded`)
6. **a wrong entity (entity_v1):** the answer names an office (case-insensitive whole phrase, from the set of `office` values in that case's data source) that is not the office of a source row and does not appear in a source row's title or text.
   - Evidence: flow q01 named row 59's office instead of row 18's.
   - Known limit: full office names only, no acronyms or nicknames.

**Correct AI answer:** every `must_include` group is present in the AI answer, and it is not wrong.
The `must_include` check reads only the AI answer, never the list (titles in the list can contain the same words).

**Answerable case** (`expects_not_found: false`):

- **Helpful** = no wrong AI answer, AND (a correct AI answer, OR **at least one** labelled source row is in the shown list).
- A fact-free or incomplete AI answer is not wrong; the case is still helpful if a source row is listed.
- A `not_found` message on an answerable case is not helpful (false "not found").

**Trap** (`expects_not_found: true`, flow q10):

- **Clean** = no AI answer is shown: the path is `not_found`, a list-only path (`guard_fired`, `answer_error`, `not_about`) or `answer_not_found`. A trap on the `answer` path is not clean, whatever the answer says.
- **Trap with an unrelated list:** a clean trap whose shown list is not empty (every listed row is unrelated, since a trap has no source row). Not unsafe, but counted and reported.
- Traps are not in the helpfulness count. They are reported as their own row.

**Unsafe** = the case has a wrong AI answer. Counted on all cases, traps included.

**Out-of-scope cases** (the existing `out_of_scope` flag): scored on Unsafe only, as today.

### The three numbers

| Metric | Numerator | Denominator |
|---|---|---|
| Helpfulness | answerable cases that are helpful | answerable cases |
| AI answer accuracy | `answer`-path replies that are correct (a trap's `answer`-path reply is never correct) | replies on the `answer` path |
| Unsafe | cases with a wrong AI answer | all cases |

- Also reported: traps clean / traps, traps with an unrelated list / traps, source-row coverage (below), and the path counts.
- **Reported per set (e2e34, taglish10, flow13) and in total, always as counts `n/N`.** A percentage may follow a count, never replace it.
- Per case: id, path, result ids, source rows found (place in the list), correct / wrong / helpful flags, and the reason codes (`must_include missing`, `wrong_row`, `entity`, ...). Ids, numbers and codes only on screen; the full texts go in the run file.

### Multi-source cases

- For helpfulness through the list, **any one** labelled source row in the list is enough (q05: 28 or 8; q06: 44, 21 or 29).
- **Source-row coverage** is a separate number: per case `k/n` (labelled source rows shown / labelled source rows), and in total `Σk/Σn` over answerable cases.
- q07: row 7 only. Row 9 (the second part) is not counted, as recorded on 2026-11-10.

---

## 1. Real-data evaluation harness

### Files

- `src/archways_assistant/evalflow.py`: the scorer (scorer_v1) and the case loader. Pure functions, unit-tested with hand-written replies.
- `scripts/eval_flow.py`: runs sets through Ollama and prints the per-case lines and totals.
- Run files go to `data/local/runs/` (gitignored: they hold announcement text).

### The pipeline per case (the full UAT flow)

1. `check_question`.
2. **Query call:**
   - `e2e_query_v1`, filled with the case's `now`, `render_qwen3`, raw.
   - `num_predict` 64 (assistant-ts `N_PREDICT.query`), `num_ctx` 2048 (`N_CTX`), no format (the phone sends no grammar).
3. `parse_query_reply`.
4. **Search, the on-device equivalent:**
   - `feedindex.search_feed` (`and_v3`), the reference that `feed_vectors.json` ties to `search.ts`.
   - Rows: the seed file for e2e34 and taglish10, the snapshot (`load_snapshot`) for flow13 and the held-out set.
5. **`assistant.flow()`, with budget switched off:**
   - A new keyword-only `budget="off"` in Python `flow()`. It skips the speed/tokens rule but keeps the `n_ctx` rule, because that is capacity, not speed.
   - The default stays `"on"`, and a test proves the default path is byte-identical. TS is not touched.
   - Case tokens: the `prompt_eval_count` of the case part, as in `measure_snapshot_budget.py`.
6. **Answer call:** `e2e_answer_v1`, `num_predict` 200 (`ANSWER_N_PREDICT`), `num_ctx` 2048.
7. The guard, the label and the list, exactly as `flow()` builds the final text.

### Cold settings (ADR 0002)

- One `ollama serve` with `OLLAMA_NUM_PARALLEL=1`.
- `num_gpu` 0, `keep_alive` 0.
- `temperature` 0, `top_k` 1, `top_p` 1, `seed` 42.

The run header records: git commit, Ollama version, model digest, prompt SHA-256s, rule versions (matcher, synonyms, rank, retry, gate θ, excerpt, answer prompt) and scorer_v1.

### Fixed "now" per case

- e2e34 and taglish10 keep their own `now`.
- **flow13 gets `now = 2026-11-10T10:00:00+08:00`** (the live-run day; the snapshot rows were published 2026-11-06 to 2026-11-07, so all fall inside a 7-day or 30-day window). The harness prints how many rows are visible at that instant.
- The held-out set gets its own fixed `now` (section 2).

### Query-reply cache

- Changes (a)–(e) don't change the query prompt, so the query replies can be reused.
- The cache is keyed by model digest, the rendered prompt's SHA-256 and the options.
- It is used only after the baseline has been run twice with identical query replies.
- Answer calls are always re-run.

### flow13 as scored cases (STOP point)

- New gitignored file `data/local/flow_cases.jsonl`, in the e2e case format plus `data: "snapshot"`.
- I propose `source_ids` (from the confirmed labels: q01 18, q02 57, q03 50, q04 39, q05 28+8, q06 44+21+29, q07 7, q08 56, q09 53, q10 trap, q11 16, q12 10, q13 14) and `must_include` groups (from your `expected` text and the snapshot rows), plus any `must_not_include`.
- **Then I stop for your confirmation.** After confirmation, the file's SHA-256 is recorded in the devlog, and it is never edited (a fix is a new file version).

### Baseline

1. Run e2e34, taglish10 and flow13 on the current system: query v1, answer v1, and_v3, newest first, first 500 characters, guard v-current, budget off.
2. Run it twice. The two runs must be identical; if not, report the differences, and every later comparison uses two runs.
3. **Scorer audit (STOP point):** I list every case flagged wrong or unhelpful with its reason codes. You confirm the flags before scorer_v1 and the baseline are frozen.
   - A scorer bug found after the freeze is fixed as scorer_v2, and the dev sets are re-scored from saved run files. The held-out baseline cannot be re-scored (section 2), so scorer_v1 must be right first.

---

## 2. Held-out protocol (FROZEN 2026-11-14)

### The script, `scripts/eval_heldout.py PATH --config baseline|final`

- Runs the same pipeline and scorer_v1 as section 1.
- **Fixed `now = 2026-11-14T10:00:00+08:00` for every held-out case,** written here before the baseline and never changed. A `now` field in the file is not read. This also keeps the snapshot rows (published 2026-11-06 and 2026-11-07) inside the model's usual 30-day window in both runs.
- **Prints only:**
  - the file's SHA-256 and the case count
  - the config's rule versions and prompt SHA-256s
  - the totals of section 0, for answerable cases, traps and all cases (counts)
- **Prints no** per-case line, question, reply or id. Writes **nothing** to disk, and uses no query cache (no read, no write).
- On a malformed file it prints the line number and the field name only, never a value.
- **File format** (written into the script's docstring): the e2e JSONL fields (`id`, `question`, `source_ids`, `must_include`, `must_not_include`, `expects_not_found`, optional `wrong_claims`, `superseded`, `out_of_scope`), plus `data: "snapshot"`. `source_ids` must exist in the snapshot.
- `tests/test_e2e_harness.py::test_no_code_reads_the_held_out_file` stays: the path comes only from the command line.

### The rule

- **The held-out set is run at most twice:**
  1. once as the baseline, after scorer_v1 and the baseline are frozen (section 1)
  2. once after all fixes in section 3 are frozen
- **Never in between,** and never to choose between changes.
- **You run it yourself.** Claude Code never runs `eval_heldout.py`, never opens or reads the file, and never asks for its contents. You paste the totals; they go into the devlog with the file's SHA-256, which must be the same in both runs.
- Recorded in ADR 0007 (PROPOSED, 2026-11-14): no training, and this held-out protocol, replacing ADR 0002's Gate 2.

---

## 3. Improvement order

### Rules for every change

1. **Pre-registered:** the rule, its version name, any frozen data file and the hand-written vectors are committed before any run. After that the rule is never tuned; a change is a new version.
2. **Parity:**
   - The Python reference (`fakebackend.py` / `feedindex.py` / `assistant.py`) and the TS port (`assistant-ts`) change together.
   - Vectors exported by the existing generators, run on Node and the Hermes CLI.
   - At least one mutation check per rule, restored afterwards from a copy.
3. **Cumulative:** each change is tested on top of every earlier kept change, and compared with that state (and with the baseline).
4. **"Nothing gets worse",** on every dev set (e2e34, taglish10, flow13) separately. A change is kept only if, on each set:
   - the helpful count does not fall (on the total; every per-case helpful → not-helpful regression is still listed by id in the report)
   - no case becomes unsafe that was safe before (per case, not just the total)
   - the number of wrong AI answers does not rise
   - Traps are reported separately: clean count and path per trap.
5. **Run order:** a retrieval-only replay first (source-row places, trap results; no model calls), then the full cold run.
6. **Per change I report:** the targeted cases before and after, every case that changed, and the decision.

### (a) rank_v1: rank matched rows by overlap with the raw question, before the 5-result cut

- **Rule:** `post-uat-and_v4-and-date-ranking.md`, section 2, steps 1–6, unchanged.
  - Content words from the raw question.
  - Date and number anchors via `claims()`, weight 3.
  - `points = words + 3 × anchors`.
  - Found in title + full text.
  - Ranked over all matched rows; newest first only as the tie-breaker; then the cut.
  - `rank_stopwords_v1.json` is written as listed there.
- **Contract:**
  - The results are no longer newest first. A new contract version changes the schema `$comment`.
  - `search(arguments, { question })` in TS, and the question is passed in Python.
- **Vectors:** the `rank` list in that plan.
- **Targets:**
  - q01: row 18 was 10th of 17 matches for `office`; "outing"/"suspension" should lift it.
  - q11: row 16 was 5th (last); the Nov 30 anchor should put it 1st.
  - Any dev case whose source row matched but was cut (the baseline replay lists them).
- **Could get worse:**
  - A row sharing generic words or a date with the question outranks the right, newer row. For example, superseded announcements: the old and new rows share words, and the tie-break by newest only applies on equal points.
  - The model sees a different first result, so answers can change on cases that are right today.
  - Index time on the phone (reported).

### (b) retry_v1: zero-result retry with the question's content words

- **Rule** (new):
  - **Fires only when** the model's arguments return 0 results (not on `query_invalid`).
  - **New query:** the question's content words, extracted as in rank_v1 (dates blanked, and_v3 tokenizer, no digits, matcher stopwords + `rank_stopwords_v1`). With no content words, there is no retry and the path stays `not_found`.
  - **Match:** a row matches if it contains **at least one** content word (and_v3's per-word test, plurals and the active synonym version). A retry with AND over every word would almost always return nothing again.
  - The model's other arguments are kept. The order is rank_v1, then the cut.
  - The outcome records `retry: true`. The log has numbers only.
- **Vectors:**
  - a model query with 0 results that is retried and finds rows
  - a question with only stopwords (no retry)
  - a question with only a date (no words, so no retry)
  - a retry that also finds nothing
  - a retry that respects the model's `days`
  - the rank order of the retry results
- **Targets:**
  - q13: `pasok` → 0 results; the retry words "pasok second term" should reach row 14 ("Second Term").
  - Every answerable dev case with 0 results at baseline (listed by the baseline).
- **Could get worse:**
  - **Traps:** cases that are `not_found` today (q10, the e2e and Taglish not-found cases) will now get results, so the model may answer from an unrelated row.
  - Pre-registered decision: if (b) breaks "nothing gets worse" only on traps, (b) is held and tested again together with (d), as one step (b+d). If it breaks an answerable case, it is dropped.

### (c) and_v4: "pasok" → class

- **Rule:** `post-uat-and_v4-and-date-ranking.md`, section 1, unchanged.
  - The frozen `contracts/search_synonyms_v2.json` = v1 + `"pasok": ["class"]`.
  - Its vectors as listed there.
- **Targets:** q13 at the query step (if (b) has not already fixed it, the gain may be zero; that is reported, not hidden).
- **Could get worse:**
  - taglish-08's trap ("May pasok ba sa November 16-18?"): retrieval stops being clean, and ann-007 (library hours on those dates) can rank first through the date anchor.
  - "classroom" / "classification" substring matches.
  - If (c) adds no helpful case and breaks nothing, it is still kept only if it changes at least one case for the better; otherwise it is dropped (no change without evidence).

### (d) gate_v1: answerability gate

- **Rule:** that plan's section 2, step 7.
  - The gate passes if the top result's `points × q ≥ p × possible`.
  - If it fails, the new path is `not_about`: no answer call; a header, then the list. The header is generated, the path is added to `PATHS`, and ADR 0004 gets an amendment.
  - **Header (user, 2026-11-14):** "I couldn't find an announcement that answers this exactly. These may be related:"
- **Fitting θ (the only fitted number):**
  - θ comes from the grid {0, 1/4, 1/3, 1/2, 2/3, 3/4}, fixed now.
  - It is fitted on **e2e34 and taglish10 only**, by exact replay of the saved (a)–(c) run files. The gate only turns `answer` paths into list paths, so no model call is needed.
  - The pick is the largest θ at which the helpful count and the correct-AI-answer count are both unchanged from θ = 0.
  - flow13 is a read-out after θ is frozen.
- **Vectors:** the `p/q` boundary (on it and just under it), `possible = 0` (the gate passes), a retry result that fails the gate.
- **Targets:**
  - q01's wrong-office answer, if row 18 is still not first.
  - Traps that get rows from (b) or (c).
- **Could get worse:**
  - Correct answers from a row whose wording differs from the question (low overlap) are replaced by the list. That is still helpful if the row is listed, but AI-answer counts fall.
  - Taglish questions have fewer matching content words, so they fall under θ more often.

### (e) excerpt_v2_centred: the 500-character window centred on the matched words

- **Rule** (new detail, pre-registered here):
  1. Take the anchor position in the body's plain text: the first found date anchor of the question; otherwise the first found question content word (rank_v1's per-word test); otherwise the first whole-word match of a query word.
  2. If there is no anchor, or the anchor's match ends within the first 500 code points, the excerpt stays the first 500 (unchanged).
  3. Otherwise `start = min(anchor − 250, length − 500)`, moved forward to the next whitespace within 30 code points, with a `…` prefix. Everything is counted inside 500 code points.
- **Version:** `excerpt_v2_centred`, a generator constant, and a new contract version (internal phone setting, ADR 0006).
- **Vectors:** an anchor inside the first 500; an anchor at 509; an anchor near the end; title-only matches; a surrogate pair at the cut; the whitespace snap.
- **Targets:** q08 (the banned items at characters 509–590 of row 56).
- **Could get worse:**
  - **e2e-003** (the long-body trap): the deadline after character 500 becomes visible, so a correct answer would hit its frozen `must_not_include`.
  - **Exception, recorded 2026-11-14 before any run (user):** under (e), e2e-003 is reported **outside** the "nothing gets worse" check, with this reason: its `must_not_include` assumes the fact is hidden past character 500, which (e) changes. Its result is still printed. Its label is not edited.
  - The text before the window (a heading, the date line) is lost, so supported claims change for the guard.
  - The model may read the `…` start as a full sentence.

### (f) answer prompt v4 = v1 + one sentence (false "not found")

- **Rule:** `prompts/e2e_answer_v4.txt` = v1 plus this one sentence, written now and not changed after any run:
  > "Write the not-found sentence only if none of the announcements answers the question; if one does, even if it is not the first, answer from that one."
  - A test checks that v4 is v1 plus exactly that sentence.
  - `generated.ts` is regenerated (new SHA-256).
  - The leak tests (`tests/test_prompts.py`) must pass. The sentence quotes no eval question.
  - SYSTEM_TOKENS_MAX (300) is checked for v4.
- **Attempted only if** the state after (a)–(e) still has at least one answerable dev case on `answer_not_found` with a source row in the results.
- **Targets:** `answer_not_found` with the source row present (q11 at baseline: row 16 was 5th).
- **Could get worse:**
  - Traps and weak results now get answers, so Unsafe can rise. (d) runs before it to limit this.
  - Answers can change on every case, because the system turn changes.

### Then

1. Freeze every kept version.
2. Re-export the phone flow test (`export_flow_test.py`).
3. One phone smoke run of flow13 (timings and paths; not a score).
4. You run the held-out final.
5. A devlog entry with the per-set and total counts, baseline against final.

---

## Decisions (user, 2026-11-14), folded in above

1. **Traps:** a separate "clean" row = no AI answer shown (`not_found`, list-only or `answer_not_found`). Traps that show an unrelated list are counted too (not unsafe).
2. **Multiple source rows:** helpfulness needs any one source row shown; coverage `k/n` is reported separately.
3. **"Nothing gets worse":** Unsafe case by case (no new unsafe case). Helpfulness on totals, but every per-case regression is listed by id in each report.
4. **e2e-003 under (e):** reported outside the check, with the reason (section 3 (e)).
5. **Fixed now:** flow13 2026-11-10T10:00+08:00; held-out 2026-11-14T10:00+08:00 (section 2).
6. **Gate header:** "I couldn't find an announcement that answers this exactly. These may be related:"
7. **ADR 0007:** drafted as PROPOSED.

## Known product limitation (recorded, not fixed in this phase)

- **The model's query usually asks for the last 30 days** (`days` 30), so evergreen announcements (dress code, uniform rules, Arch guidelines, the Good Moral process) become unsearchable a month after they are published.
- Not fixed now: it needs a change to the query rule or the window, which is outside this phase's order. The fixed `now` values keep it out of the scores; it does not stop it in real use.

## 2026-11-14 (user): audit accepted; scorer_v1 and Step 2 frozen; private report added

- **scorer_v1 frozen as is,** at commit `9bf6e72` (`src/archways_assistant/evalflow.py`, SHA-256 with LF line endings `44cd6308…4691`; pinned by `tests/test_evalflow.py::test_scorer_v1_is_frozen`).
  - **Known limitation:** scorer_v1 catches only wrong dates, numbers, office names and listed phrases. It cannot catch an answer that mixes up which listed announcement says what. Example: flow q06 baseline says the dress code is "in the second and third announcements"; only the third is.
- **Dev baseline frozen:** `data/local/runs/baseline-1.json` (identical to `baseline-2.json`), totals in the devlog of 2026-11-14.
- **Amendment to section 2, added before its freeze took effect (user):** `eval_heldout.py --private-report PATH`.
  - Writes one block per case (id, question, flags and reason codes, query arguments, the final text the student would see) to PATH, for the user's manual review of answers the scorer passes.
  - PATH must be outside the repository (checked on the resolved path, ignoring case, before any model call) and must not exist yet.
  - The four printed lines are unchanged. Without the option nothing is written; a run that fails writes no report.
  - **Only the user reads the report.** It never enters the repo, the devlog or a chat, and Claude Code never opens it.
- **Step 2 frozen** at commit `9bf6e72` (`scripts/eval_heldout.py`). The next change to it is adding `--config final` when every change in section 3 is frozen.
- **The held-out baseline may now be run, once,** by the user, at a commit whose code equals `9bf6e72`, with a clean tree. Its first printed line shows `"commit"` and `"tree_dirty": false`.

## 2026-11-14 (user): held-out baseline done; human review added to both held-out runs

- **Held-out baseline** (run by the user, once): file SHA-256 `4707c20791744d00fbf63a3f793c4a0a0c7061db06392d9e913fa9082f3a2342`, 20 cases. **The final run must show the same hash.**
- **Human review is part of both held-out runs.** The user reviews the private report of the baseline and of the final run the same way. Both runs report Unsafe twice, side by side: **scored** (scorer_v1) and **human-reviewed**.
- **Second known limitation of scorer_v1:** it can't detect a reply that contradicts its source on a yes/no question (a negation: "allowed" where the source prohibits). scorer_v1 is not changed; the human review covers this.
- **Protocol deviation, recorded:** the baseline private report was viewed by the user's external advisor (a chat assistant), not by the user alone. No fix will be designed from it. Claude Code has not seen the report or the file.
- **No reordering:** the improvement order in section 3 stays as pre-registered. Nothing in it is changed because of this run.

## 2026-11-14: rank_v1 rule, pre-registered (section 3 (a))

Committed with `contracts/rank_stopwords_v1.json` and the hand-written `tests/vectors/rank_vectors.json`, **before any rank_v1 code or run**. It makes `post-uat-and_v4-and-date-ranking.md` section 2 steps 1–6 exact; where the wording differs, this text is the rule. Scored on the dev sets only.

1. **Candidates:** every row the matcher (and_v3) and the days window accept. No cut yet.
2. **Question anchors:** `claims(question)` (`e2escore.claims` / guard-ts `claims`, unchanged).
   - Date anchors are its (month, day) pairs.
   - Number anchors are its numbers. A date's year is a number; its day is not.
   - So "November 16-18" gives the date 11-16 and the number 18.
3. **Question content words:**
   - Take the lowercased question with every parsed date span blanked, exactly as `claims()` blanks it.
   - Split it into maximal runs of and_v3 word characters (`_`, L*, Nd: `is_word_char` / `WORD_RANGES`).
   - Drop: tokens with a decimal digit; tokens of one code point; the matcher's stopwords (`AND_V2_STOPWORDS`, the stopwords and_v3 uses); and `rank_stopwords_v1`.
   - Keep the first occurrence of duplicates, in question order.
4. **Found, per row** (lowercased title, and lowercased whole plain-text body, not the excerpt):
   - **A content word w** is found by the matcher's own test for a one-word query w: some alternative in [w, *synonyms(w)] is a substring of the title or of the body, or w's plural alternative is a whole word in the title or the body.
   - **A date anchor** is found if it is in `claims(title + "\n" + body).dates`.
   - **A number anchor** is found if it is in `merged_claims([title + "\n" + body]).numbers` (the row's numbers, its dates' years and its dates' day numbers).
5. **Score:**
   - `points = words_found + 3 × anchors_found` and `possible = n_words + 3 × n_anchors`.
   - Integers only. The weight 3 is fixed.
6. **Order:** points descending, then published descending, then id ascending. Then the cut to `limit`.
   - With `possible = 0`, every row scores 0 and the order is exactly today's.
7. **Where it applies:**
   - The search takes the raw question: Python `search_feed(..., question=..., rank="rank_v1")`; TS `searchRows(rows, args, nowMs, { question, rank: "rank_v1" })`, with `AssistantDeps.search(args, { question })`.
   - The query arguments and the contract are unchanged.
   - The results' order is now rank_v1, not newest first. This is an internal phone setting (ADR 0006).
8. **Parity:**
   - Python and TS each pass `rank_vectors.json`, and Node and the Hermes CLI run it.
   - guard-ts `claims` is exported and reused, never copied.
9. **Mutations to check:**
   - ranking after the cut
   - the excerpt in place of the full text
   - weight 1 in place of 3
   - the tie-break reversed
   - one-character tokens kept
10. **Keep or drop:** kept only if the "nothing gets worse" rule (section 3) holds on e2e34, taglish10 and flow13 against the frozen baseline.
    - The query replies are the baseline's: the prompts are unchanged, and the baseline was deterministic.
    - The answer calls are re-run cold.

## 2026-11-14: rank_v1 result: KEPT (by the pre-registered rule)

- **Run:** `eval_flow.py --rank rank_v1 --reuse-queries baseline-1.json`, commit `92b300e`, clean tree, the frozen dev baseline's query replies, answer calls cold. Run file `data/local/runs/rank_v1-1.json`.
- **Retrieval replay (no model):**
  - q01: row 18 went from cut to 1st. q11: row 16 from 5th to 1st. e2e-032: its source from 2nd to 1st.
  - Order changed, but no source row lost its place, in e2e-021 (trap), taglish-03 and q11's other rows. Nothing else changed.
- **"Nothing gets worse": OK on every set.**

  | Set | Helpful | AI correct | Wrong AI answers | New unsafe | Traps clean |
  |---|---|---|---|---|---|
  | e2e34 | 22 → 22 | 18 → 18 | 0 → 0 | none | 10/10 → 10/10 |
  | taglish10 | 5 → 5 | 3 → 3 | 0 → 0 | none | 3/3 → 3/3 |
  | flow13 | 10 → 11 | 4 → 5 | 1 → 0 | none | 1/1 → 1/1 |
  | **Total** | **37/42 → 38/42** | **25/28 → 26/28** | — | — | 14/14 → 14/14 |

  - Unsafe (scored) 1/57 → 0/57. Coverage 40/45 → 41/45. Paths unchanged in count.
  - The only answer reply that changed is q01's. It now names the Office of the Secretary-General, from row 18: helpful, correct, no longer unsafe.
  - q11 is still `answer_not_found` with row 16 now 1st: the model says not found with the right row first. That is (f)'s target.
- **Decision:** rank_v1 is kept. Every later step is tested with rank_v1 on.
- **Not yet changed:** the phone default stays newest first (`makeFeedSearch` rank null) until the final freeze of all kept versions.

## 2026-11-14: retry_v1 rule, pre-registered (section 3 (b))

Committed with the hand-written `tests/vectors/retry_vectors.json`, **before any retry_v1 code or run**. It makes section 3 (b) exact. It runs on top of rank_v1 (kept).

1. **When:** the model's arguments are valid (contract-checked) and the search returns **0 results**.
   - Never on `query_invalid`, and never when the arguments break the contract (a search error).
   - At most one retry.
2. **Retry words:** rank_v1's content words of the raw question (`question_terms(question).words`: dates blanked, word-character runs, digit tokens, one-character tokens and both stopword lists dropped).
   - No content words (only stopwords, or only a date): no retry, and the path stays `not_found`.
   - Anchors alone never trigger a retry.
3. **Match:** a row matches if **at least one** retry word is found by the matcher's own one-word test: substring, synonyms of the active synonym version, or plural alternative as a whole word (rank_v1's `word_found`).
   - The model's `days` and `limit` are kept, with the contract defaults when absent. The days window applies as usual.
4. **Order:** rank_v1 points (the full question: words and anchors), then newest, then id. Then the cut to `limit`.
5. **Recorded:** `retried` (true when a retry was attempted, whatever it found). The phone log carries the flag and the result count only.
6. **Parity:**
   - Python `feedindex.search_feed_retry(...) -> (results, retried)` and TS `searchWithRetry(...)` / `makeFeedSearch(..., rank, retry)`.
   - Both pass `retry_vectors.json`, on Node and the Hermes CLI.
7. **Mutations to check:**
   - AND in place of OR
   - the retry firing when the first search found rows
   - the model's days ignored
   - newest first in place of rank_v1
   - the retry on a question with no content words
8. **Keep or drop** (section 3 (b), pre-registered):
   - Compared against the rank_v1 run, with the "nothing gets worse" rule on every dev set.
   - If it breaks the rule **only on traps** (a trap no longer clean, or a new unsafe trap), (b) is **held** and re-tested together with (d), as one step (b+d).
   - If it breaks an answerable case, it is **dropped**.
   - The run reuses the baseline's query replies and re-runs the answer calls cold.

## 2026-11-14 (user): harness drift check before the final held-out run

- **Why:** the held-out script imports `eval_flow.run_case`, whose file changed after the `9bf6e72` freeze (rank, reuse, retry options). The default path must be proven unchanged.
- **The check:** `uv run python scripts/eval_flow.py --verify-baseline data/local/runs/baseline-1.json --out data/local/runs/<name>.json`.
  - It runs the baseline configuration (rank off, retry off) on every dev case with the frozen baseline's query replies, and re-runs the answer calls cold.
  - It requires every case's arguments, search results, case tokens, answer reply, path, final text and full score to equal `baseline-1.json`. Otherwise it exits 1.
  - Tests (`tests/test_verify_baseline.py`) also pin the part a reuse run skips: with no saved reply, `run_case` makes the query call with `flow()`'s own prompt and searches newest first.
- **Rule:** this check must print `VERIFY OK` at the commit the final held-out run uses, with a clean tree, before that run.
- **Result, 2026-11-14:**
  - The first run (`fa8e238`) reported 0/57 identical on `score` only. The cause was a bug in the comparison: in-memory tuples against saved lists.
  - Fixed in `9168e58`, with a test. The first run's saved records then compared 57/57 identical.
  - A clean end-to-end run at `9168e58` (clean tree): **VERIFY OK, 57/57 identical.**

## 2026-11-14: retry_v1 result: DROPPED (by the pre-registered rule)

- **Run:** `--rank rank_v1 --retry retry_v1 --reuse-queries baseline-1.json` (`data/local/runs/retry_v1-1.json`).
  - The header says `17937f3-dirty`: the comparison fix (`9168e58`) was committed in the seconds between the queued job's clean `git status` and the header.
  - The only difference is inside `verify_baseline()`, which this run never calls. The run path is `17937f3`'s.
- **Retrieval replay:**
  - All four answerable zero-result cases reached their source: e2e-014 4th, e2e-023 1st, taglish-04 1st, q13 3rd.
  - Most traps got a list.
- **Against rank_v1:**

  | Set | Helpful | AI correct | Wrong AI answers | New unsafe | Traps clean |
  |---|---|---|---|---|---|
  | e2e34 | 22 → 24 | 18 → 20 (of 22) | 0 → 0 | none | 10 → 8 of 10 |
  | taglish10 | 5 → 6 | 3 → 3 | 0 → 0 | none | 3 → 3 of 3 |
  | flow13 | 11 → 11 | 5 → 5 (of 9) | 0 → 1 | **q13** | 1 → 0 of 1 |

  - Total: helpful 38 → 41/42, coverage 41 → 45/45, traps clean 14 → 11/14, traps with an unrelated list 2 → 6/14, Unsafe (scored) 0 → 1/57.
  - **q13 (answerable) became unsafe.** The retry ranked row 51 first and row 14 3rd. The reply took 51's date ("November 20, 2026") instead of January 15.
  - **Traps no longer clean:** e2e-003, e2e-018, q10 got AI answers.
- **Decision:** the rule says "if it breaks an answerable case, it is dropped". q13 is answerable and newly unsafe, so retry_v1 is **dropped**, not held for (d).
  - Its code stays in the repo, off by default (phone default off, harness `--retry` off). Any later retry is a new pre-registered version.
- **Observation (not a scorer change):** e2e-018's reply states "The enrollment fee waiver program is still accepting applications." It is an invented fact on a trap, with no date, number or office, so scorer_v1 does not flag it. A human review would. This is a third kind of fact scorer_v1 can't see, next to the two recorded limitations.
- **Next:** (c) and_v4, tested on top of rank_v1 alone.

## 2026-11-14 (user): experiment pre-registered for later: "retry_v1 + gate_v1 combined"

- **Registered before any (d) result exists.** gate_v1 is not built, its θ is not fitted, and nothing about (d) has run. Recorded at this commit, before (c) runs.
- **When:** tested only if (d) gate_v1 is kept. Otherwise it is never run, and retry stays off for good.
- **What:** retry_v1, unchanged (`60f54c1` rule, `17937f3` code), switched on together with the kept gate_v1, on top of every kept change at that point. No retry or gate parameter is re-tuned for it: θ is the one (d) froze.
- **Rules:** the same as section 3:
  - nothing worse on every dev set (e2e34, taglish10, flow13) against the state with the kept changes and the retry off
  - no new unsafe case
  - traps reported separately
  - the baseline's query replies, answer calls cold
- **If it fails any rule, retry stays off for good.** No retry_v2 is built in this phase.

## 2026-11-14 (user): scorer_v1 blind spot: observations

scorer_v1 sees only dates, numbers, office names and listed phrases. Observed cases of what it can't see (none changes the frozen scorer; the human review covers them):

1. **Held-out baseline (user review):** a reply contradicting its source on a yes/no question ("allowed/encouraged" where the source prohibits).
2. **Dev, retry_v1 run (e2e-018, a trap):** an invented claim with no date, number or office: "The enrollment fee waiver program is still accepting applications."
3. **Dev baseline (flow q06):** mixing up which listed announcement says what ("second and third announcements").

## 2026-11-14: and_v4 rule, pre-registered (section 3 (c))

Committed with `contracts/search_synonyms_v2.json` and the hand-written `tests/vectors/and_v4_vectors.json`, **before any and_v4 code or run**. Tested on top of rank_v1 (kept). retry_v1 stays off (dropped).

1. **and_v4 = and_v3's matching rules with `search_synonyms_v2`:** v1's map plus `"pasok": ["class"]`, and the same extra stopwords. v1 stays frozen for and_v2/and_v3.
   - A synonym is a plain substring, so `class` also matches "classes", "classroom" and "classification" (by design; vector S1).
2. **rank_v1 under and_v4** finds a question word through the active synonym version (`word_found` with v2), so the question word "pasok" is found in a row with "class" (vector S4).
   - rank_v1's content words, anchors, weights and stopwords are unchanged.
3. **Parity:**
   - Python `fakebackend` matcher "and_v4"; `rank.word_found` / `points` take the synonym map of the matcher in use; `search_feed(..., matcher=)`.
   - TS: `SYNONYMS_V2` generated; `searchRows` / `rankScorer` / `makeFeedSearch` take the matcher.
   - Both pass `and_v4_vectors.json` (expected ids and points under and_v4 **and** and_v3), on Node and the Hermes CLI.
4. **Mutations to check:**
   - v1 synonyms under and_v4
   - v2 synonyms under and_v3
   - rank_v1 finding words with v1 under and_v4
5. **Keep or drop:**
   - The "nothing gets worse" rule on every dev set, against the rank_v1 run (`rank_v1-1.json`). The baseline's query replies are reused, and the answer calls re-run cold.
   - Reported as the pre-registered plan asks: q13 (row 14's place); taglish-08 (retrieval clean or not; the path; honest or not); and whether any reply presents a non-class row as being about classes.
   - A hurt answerable case or a new unsafe case → dropped.
   - The trap rule is the section 3 one: traps reported separately. A trap that stops being clean counts against "nothing gets worse" only through Unsafe; the pre-registered (b) hold option does not apply to (c).

## 2026-11-14: and_v4 result: KEPT (by the pre-registered rule)

- **Run:** `--rank rank_v1 --matcher and_v4 --reuse-queries baseline-1.json`, commit `000e49f`, clean tree (`data/local/runs/and_v4-1.json`). Compared against the rank_v1 run.
- **Retrieval replay:** only q13 changed. Row 14 went from not retrieved to 1st.
- **"Nothing gets worse": OK on every set.**

  | Set | Helpful | AI correct | Wrong AI answers | New unsafe | Traps clean |
  |---|---|---|---|---|---|
  | e2e34 | 22 → 22 | 18 → 18 | 0 → 0 | none | 10/10 → 10/10 |
  | taglish10 | 5 → 5 | 3 → 3 | 0 → 0 | none | 3/3 → 3/3 |
  | flow13 | 11 → 12 | 5 → 6 | 0 → 0 | none | 1/1 → 1/1 |
  | **Total** | **38 → 39/42** | **26/28 → 27/29** | — | — | 14/14 → 14/14 |

  - Unsafe (scored) 0/57 → 0/57. Coverage 41 → 42/45.
- **Pre-registered report items:**
  - **q13:** row 14 is 1st, and the path went from `not_found` to `answer`, correct.
    - Note: the reply is "The Second Term of Academic Year 2026-2027 will officially commence on January 15, 2027. No official announcement was found for your question."
    - It is the right fact followed by the not-found sentence. scorer_v1 counts it correct (`must_include` present, nothing wrong). The trailing sentence contradicts the answer, which is the kind of thing only the human review sees.
  - **taglish-08:** retrieval stays clean. The model's query was "swimming pool", not "pasok", so the synonym never applied. The path is `not_found`, honest. The trap is not exercised by this dev run.
  - **No reply presents a non-class row as being about classes.** q13's is the only answer reply that changed.
- **Decision:** and_v4 is kept. Every later step runs with rank_v1 + and_v4. The phone default changes only at the final freeze.

## 2026-11-14 (user): fix (g) strip_nf_v1, pre-registered (tested after (f))

Committed with the hand-written `tests/vectors/strip_nf_vectors.json`, before any code or run, and before (d) runs. Evidence: flow q13 under and_v4. Its reply gave the right answer, then the exact not-found sentence.

1. **Where:** in the flow, on a reply that would reach the guard. That is, after the ASCII-whitespace strip and after the existing "the reply is exactly the not-found sentence → `answer_not_found`" check.
2. **Rule:** if the reply contains the exact not-found sentence (`NOT_FOUND_MESSAGE`, case-sensitive, byte-exact) together with other text:
   - remove every occurrence of the sentence
   - strip ASCII whitespace from both ends; inner spacing is left as it is
   - if nothing is left, the path is `answer_not_found`. Otherwise the remainder goes to the guard and on, as the reply.
3. A near miss or a different case is not the sentence and stays (vectors N7, N8).
4. **Parity:** Python `flow()` and TS `flow.ts`, both checked against `strip_nf_vectors.json`, plus new flow vectors. It is a flow setting with a version name, off until kept.
5. **Order and rule:** tested after (f), on top of every kept change, under section 3's rules. That means "nothing gets worse" on every dev set, no new unsafe case, traps reported, and the AI-correct comparison case by case.

## 2026-11-14: gate_v1 rule, pre-registered (section 3 (d))

Committed with the hand-written `tests/vectors/gate_vectors.json`, **before any gate code, fit or run**. On top of rank_v1 + and_v4 (kept).

1. **Decision:** for a search with at least one result, take the **top result** (first after rank_v1) and its full row (lowercased title and whole plain-text body). The gate passes if `points × q ≥ p × possible` for θ = p/q, with rank_v1's points and possible under the matcher in use (its synonyms). `possible = 0` always passes.
2. **If it fails:**
   - The new path is `not_about`: no counting and no answer call.
   - The text is the results list with its header line replaced by "I couldn't find an announcement that answers this exactly. These may be related:" (the user's text).
   - For scoring, `not_about` is a list-only path (section 0 already names it): the shown list is the results, and there is no AI answer. The harness passes the plain results list to the frozen scorer_v1 for it, and the scorer's code is unchanged.
3. **θ grid, fixed now:** {0, 1/4, 1/3, 1/2, 2/3, 3/4}.
4. **Fit (user's conditions, 2026-11-14):**
   - **Fit sets:** e2e34 and taglish10 only.
   - **Method:** an exact replay of the saved rank_v1 + and_v4 run (`and_v4-1.json`). The gate only removes answer calls, so no model call is needed.
   - **Pick:** θ\* is the **largest** θ in the grid at which, on the fit sets, compared with θ = 0:
     - (i) **no case that was AI-correct loses it** (no correct AI answer lost, case by case)
     - (ii) the helpful count does not fall
     - (iii) no case becomes unsafe
   - If θ\* = 0, the gate does nothing and (d) is dropped.
5. **Read-out and keep rule:**
   - With θ\* frozen, the replay is applied to every dev set (flow13 included) and compared with the rank_v1 + and_v4 run.
   - The check is the section 3 "nothing gets worse" rule **plus AI-correct case by case**: no case on any set may go from AI-correct to not AI-correct (helpfulness alone can't see a correct answer turned into a list).
   - Traps are reported separately (clean, unrelated list).
   - Any failure → (d) dropped.
6. **Parity:**
   - The decision function `gate_v1(question, top row, matcher, p, q)` is built in Python (`rank.py`) and TS (`rank.ts`) and checked against `gate_vectors.json` on Node and the Hermes CLI **before the fit**.
   - The `not_about` flow path is built (Python `flow()`, `flow.ts`, `PATHS`, generated strings, ADR 0004 amendment) only if (d) is kept.
   - A confirming cold run with the integrated flow must then reproduce the replay case by case.
7. **Mutations to check:** `≥` → `>`; the excerpt in place of the whole body; the second result in place of the first; v3 synonyms under and_v4.
8. **Then:** if (d) is kept, the registered "retry_v1 + gate_v1 combined" experiment follows, with θ\* unchanged.

## 2026-11-14: gate_v1 result: DROPPED (θ* = 0 by the pre-registered fit)

- **Before the fit:**
  - The decision function was built in Python and TS (`4047827`). It passes `gate_vectors.json` on Python, Node and Hermes.
  - G6 was added by hand (`c7d0e24`) after the mutation "excerpt in place of the body" survived G1–G5.
  - All pre-registered mutations were caught: `≥` → `>`, the excerpt, the second result, and v3 synonyms under and_v4.
- **Fit:** `eval_flow.py --gate-fit data/local/runs/and_v4-1.json`, an exact replay on e2e34 + taglish10 against θ = 0.

  | θ | Gated | AI-correct lost | Helpful | New unsafe | Passes |
  |---|---|---|---|---|---|
  | 0 | — | — | 27 → 27 | — | yes |
  | 1/4 | taglish-02 | taglish-02 | 27 → 27 | — | no |
  | 1/3 | e2e-021, taglish-02 | taglish-02 | 27 → 27 | — | no |
  | 1/2 | 5 cases | e2e-026, taglish-02 | 27 → 27 | — | no |
  | 2/3 | 7 cases | 4 | 27 → 27 | — | no |
  | 3/4 | 11 cases | 8 | 27 → 27 | — | no |

- **θ\* = 0: the gate does nothing, so (d) is dropped** (rule 4). flow13 was not read out; the rule needs θ\* > 0 for that.
- **Why the smallest step fails:**
  - taglish-02 ("anu oras ung advising sa 2nd yr?") is correct at θ = 0, but its top row scores 1 of 8.
  - The informal spellings and "yr" are not in the row, and "2nd" is a number anchor (2, weight 3) that the row doesn't contain.
  - This is the Taglish risk recorded for (d).
  - The helpful count never fell, because a gated case still shows its list. That is why the fit also required no correct AI answer to be lost (user, 2026-11-14).
- **Consequences:**
  - The `not_about` flow path is **not built** (it was conditional on keeping (d)).
  - The decision function and the replay stay in the repo, unused.
  - The pre-registered **"retry_v1 + gate_v1 combined" is not run**, because (d) was not kept. **Retry stays off for good**, as registered.
- **Next:** (e) excerpt_v2_centred, on top of rank_v1 + and_v4, with the e2e-003 exception as recorded.

## 2026-11-14 (user): finding: word-overlap scoring is biased against Taglish and informal questions

- **Evidence:** taglish-02 ("anu oras ung advising sa 2nd yr?") scores 1 of 8 against its correct row (ann-005).
  - Informal spellings ("anu", "ung", "yr") never appear in announcements.
  - Informal numbers ("2nd") become number anchors the row doesn't contain.
- **Consequence:** an overlap-based answerability gate (gate_v1) would suppress correct answers for Taglish speakers. That is why (d) was dropped: θ = 1/4 already lost taglish-02.
- **rank_v1 is unaffected:** it only reorders the rows the matcher already found. With weak overlap everywhere, the rows tie and the order falls back to newest first, as before rank_v1.
- **For any later aboutness check:** it must not rely on literal word overlap with the question alone. Taglish questions need to be part of its fit set from the start.

## 2026-11-14: excerpt_v2_centred rule, pre-registered (section 3 (e))

Committed with `tests/vectors/window_vectors.json` (13 cases; positions worked out by hand), **before any window code or run**. On top of rank_v1 + and_v4 (kept). It makes section 3 (e) exact. All lengths and positions are in code points of the row's plain-text body (the whole body, as indexed).

1. **Guard:** if lowercasing the body changes its length in code points, the excerpt stays the first 500 (vector E10). Positions found in the lowercased text would not map back.
2. **Anchor,** searched in the lowercased body, in this priority:
   - **a. A date anchor:** the date spans `claims()` parses in the body (the same patterns and blanking order) whose (month, day) is one of the question's dates. The earliest span wins.
   - **b. Otherwise a question content word:** for each of rank_v1's content words, the earliest substring match of the word or any of its synonyms under the matcher in use, or of its plural alternative as a whole word. The earliest match over all words wins (ties: the shorter match first).
   - **c. Otherwise a query word:** the same, over the matcher's groups for the model's query.
   - **d.** No anchor at all → the first 500.
3. **No move:** if the anchor ends at or before 500, the excerpt is the first 500, unchanged (E1, E11).
4. **Window:**
   - `start = max(0, min(anchor_start − 250, length − 500))`.
   - If `start > 0` and the code point before `start` is not a space (U+0020), `start` moves to just after the first space in `[start, start + 30)`, if there is one (E2; E7: none, so no move).
   - The excerpt is "…" (U+2026) followed by 499 code points from `start` (fewer at the end of the body). The total is at most 500.
5. **Scope:** the excerpt of every returned result is rebuilt this way, each from its own body. Titles are unchanged. The guard's supported claims follow the new excerpts, because they are read from the results.
6. **Parity:**
   - Python: the window function, plus `search_feed(..., excerpt="excerpt_v2_centred")`. `claims_and_rest` also returns the date spans.
   - TS: guard-ts `claimsAndRest` returns the same spans; `IndexRow` keeps the original-case plain body; `searchRows` / `makeFeedSearch` take the excerpt rule.
   - Both pass `window_vectors.json` and an integration vector through the search, on Node and the Hermes CLI. The phone default stays the first 500.
7. **Mutations to check:**
   - word priority over dates (E5)
   - no snap
   - snap backward
   - UTF-16 units in place of code points (E9)
   - the 500 boundary as `<` in place of `≤` (a vector with the anchor ending exactly at 500 is added with the code if none covers it)
8. **Keep or drop:**
   - The section 3 "nothing gets worse" rule on every dev set **with AI-correct case by case** (the user's (d) condition, applied from (d) onwards), against the rank_v1 + and_v4 run.
   - The baseline's query replies are reused, and the answer calls re-run cold.
   - **e2e-003 is reported outside the check** (the exception recorded 2026-11-14).
9. **Must report:**
   - q08: whether the banned items reach the excerpt, and the answer.
   - **The long-body trap explicitly** (the 2026-10-31 risk that a window surfaces its hidden fact): e2e-003's anchor, whether its hidden deadline enters the excerpt, its path and reply. Also any other case whose excerpt now contains a fact past character 500 that it didn't before.

## 2026-11-14: excerpt_v2_centred result: passes the keep rule with NO effect on any dev case (decision with the user)

- **Built (`aaba630`):**
  - Python `window.py` and TS `window.ts`.
  - `claims_and_rest` / guard-ts `claimsAndRest` also return the date spans (guard results unchanged: Node 461/461, Hermes 453/453).
  - `IndexRow.plain`; `searchRows(..., excerptFor)`; `makeFeedSearch(..., excerpt)` (phone default: the first 500).
  - `eval_flow.py --excerpt` / `--excerpt-replay`.
- **Vectors and checks:**
  - The 13 hand-derived window vectors, E13 (the 500 boundary, `7e27292`) and a search integration vector pass in Python, Node (285/285) and Hermes (window 15/15).
  - **Mutations,** all caught: words before dates (4 fail), no snap (6), snap backward (6), `<` at the boundary (1); TS UTF-16 units (1), words before dates (1), `<` (1).
- **Retrieval replay** (rank_v1 + and_v4, every dev case): **no excerpt changed.**
- **Cold run** (`window-1.json`, `aaba630`, clean tree): `--compare` with `and_v4-1.json` → **57/57 identical.**
  - "Nothing gets worse" with AI-correct case by case and e2e-003 outside the check: OK on every set.
  - Totals unchanged: helpful 39/42, AI correct 27/29, Unsafe 0/57, traps clean 14/14.
- **The target, q08:** not reached.
  - The rule's anchor is the *earliest* question word, and row 56 names the initiative early ("Verde" at 168).
  - So the window stays at the start, and the banned items (from 509) stay hidden.
- **The long-body trap, explicitly** (the 2026-10-31 risk):
  - e2e-003 is not exercised in this run. The model's query ("accruement deadline") retrieves nothing, so there is no excerpt.
  - If ann-004 were retrieved, its anchor would be "org" at 47. The window would not move, and the hidden deadline (at 772) would stay hidden.
  - No dev case shows any newly visible date or number.
- **Decision:** by the letter of rule 4 it passes, because nothing got worse. But it changed nothing on any dev case, including its one target, so there is no dev evidence of benefit. On the phone it would only change behaviour on unseen data. **Whether it is enabled at the final freeze is left to the user.** The code stays, off by default, until then.
- **Next:** (f) answer prompt v4 (one sentence, false "not found"), on top of rank_v1 + and_v4.

## 2026-11-16 (user): excerpt_v2_centred stays OFF at the freeze

- **Decision:** excerpt_v2_centred is **not enabled** at the final freeze. The phone keeps the first 500 code points.
  - It passed rule 4 only because nothing changed: no dev evidence of benefit (its one target, q08, was not reached), and enabling it would change behaviour only on unseen data. This applies the "no change without evidence" principle from (c).
  - The code stays in the repo, off by default, unused.
- **Why it had no effect (a design reason, recorded):** the rule anchors on the **earliest** question word (step 2b). Question words usually appear early in the body, often inside the first 500 (q08: "Verde" at 168), so rule step 3 leaves the window at the start. A fact the question names only later in the body is never reached.
- **Any revisit must be a new pre-registered version** (for example `excerpt_v3_…`), with its own rule, vectors and run. excerpt_v2_centred itself is not changed.
- **Next:** (f) answer prompt v4, then (g) strip_nf_v1, as registered.

## 2026-11-16: answer prompt v4 result: DROPPED (7 correct AI answers lost; 0 of 10 targets fixed)

- **Precondition** (section 3 (f)): met. The and_v4 run has 10 answerable cases on `answer_not_found` with a source row shown: e2e-001, e2e-005, e2e-012, e2e-029, taglish-01, taglish-03, q05, q07, q09, q11.
- **Built (`5975ead`), before any run:**
  - `prompts/e2e_answer_v4.txt` = v1 plus the registered sentence, appended to the not-found rule's line (one space before it).
  - `tests/test_answer_v4.py`: v4 is v1 plus exactly that sentence; the sentence is verbatim in this plan; v4 is frozen by SHA-256 (`84eb2bd0…1bdf`); `eval_flow.py --answer-prompt v4`, and `--verify-baseline` refuses it.
  - The leak test (`tests/test_prompts.py`) covers v4 (it reads every prompt file) and passes.
  - **SYSTEM_TOKENS_MAX:** the v4 system turn is 229 tokens (Ollama `prompt_eval_count`, raw system turn; v1: 197), under 300.
  - Mutations caught: one word of v4 changed (3 fail); the verify-baseline refusal removed (1 fail).
  - `generated.ts` was **not** regenerated: the phone default stays v1, as with every other change until the freeze. Switching would be the generator's prompt path plus a regeneration.
- **Retrieval:** the prompt changes no retrieval. Re-searching every case of `and_v4-1.json` reproduces its results, excerpts included, 57/57.
- **Cold run** (`answer_v4-1.json`, `5975ead`, clean tree, query replies from `baseline-1.json`): `--nothing-worse and_v4-1 answer_v4-1 --correct-case-by-case` → **something got worse** on all three sets.
  - Totals: helpful 39 → 39/42; AI correct 27/29 → 20/22; Unsafe 0 → 0/57; traps clean 14 → 14/14. Paths: `answer_not_found` 12 → 18.
  - **AI-correct lost (case by case):** e2e-009, e2e-025, taglish-02, taglish-06 and q13 (answer → `answer_not_found`); e2e-015 (still an answer, now missing "three"); e2e-030 (`guard_fired`, `unsupported_date:10-21`). q06 also went answer → `answer_not_found` (it was not AI-correct before).
  - **Targets:** 0 of 10 changed. All are still `answer_not_found`.
  - No helpful case was lost and no case became unsafe. The traps are unchanged, including the two with an unrelated list (e2e-021, taglish-09).
- **Decision:** **DROPPED** (rule 4). The extra sentence made the 0.6B model write the not-found sentence more often, not less. Later steps run with answer v1. The v4 file and `--answer-prompt v4` stay in the repo, unused.
- **Next:** (g) strip_nf_v1, on top of rank_v1 + and_v4 with answer v1.

## 2026-11-16: strip_nf_v1 result: KEPT (q13 fixed; nothing else changed)

- **Built (`2116739`), before any run:**
  - Python `assistant.answer_reply_text()` and `flow(..., strip_nf=)`; TS `answerReplyText()`, `startQuestion(..., { stripNf })` and `AssistantDeps.stripNf`. Default off (null) in both.
  - `strip_nf_vectors.json` (the 9 hand-written vectors) passes in Python, Node and Hermes (9/9). Five new generated flow vectors (`strip-nf-*`, one with the rule off) pass on the Node stepper and driver and on Hermes (assistant vectors 252/252). The existing vectors are byte-identical.
  - **Mutations,** all caught and restored. Python: first occurrence only (2 fail), no re-strip (6), applies when off (8), collapses inner spacing (1), case-insensitive removal (1; N8). TS: first occurrence only (4), no re-trim (8), applies when off (8), the driver drops the option (3). A case-insensitive *test* with case-sensitive removal is an equivalent mutant (same output on every input).
  - `eval_flow.py --strip-nf strip_nf_v1`, plus `--strip-nf-replay` (no model call). `--verify-baseline` refuses it.
- **Replay** (no model call) on `and_v4-1.json`: only q13 changes (path `answer` stays, text changes).
- **Cold run** (`strip_nf-1.json`, `2116739`, clean tree, query replies from `baseline-1.json`, answer v1): `--nothing-worse and_v4-1 strip_nf-1 --correct-case-by-case` → **nothing got worse** on every set.
  - `--compare`: 56/57 identical; q13 differs in text only. All 57 answer replies are identical to the and_v4 run.
  - Totals unchanged: helpful 39/42, AI correct 27/29, Unsafe 0/57, traps clean 14/14.
  - **q13:** the shown answer no longer ends with the not-found sentence. That was the contradiction scorer_v1 can't see (recorded 2026-11-14).
- **Decision:** **KEPT.** It changes one case for the better and nothing for the worse, so it also meets the "no change without evidence" principle from (c). It turns on at the final freeze, with rank_v1 + and_v4.
- **Kept set for the freeze:** rank_v1, and_v4, strip_nf_v1, answer v1. Off: retry_v1, gate_v1, excerpt_v2_centred, answer v4.
- **Next:** the "Then" list in section 3 (freeze every kept version, re-export the phone flow test, one phone smoke run of flow13, the user's held-out final).

## 2026-11-16: the freeze ("Then", steps 1–2) and the phase finding

- **Frozen (`3a7d0af`):** `src/archways_assistant/frozen.py` `FINAL` = rank_v1, and_v4, strip_nf_v1, answer v1. retry, the gate, the excerpt window and answer v4 are off.
  - `export_assistant_ts.py` writes it into `generated.ts` as `PHONE_*`, the defaults of `makeFeedSearch()` and `askAssistant()`.
  - `eval_heldout.py --config final` runs it: same fixed now, the same four printed lines (the settings line adds `rank`/`retry`/`excerpt`/`strip_nf`, and `matcher` reads and_v4), and `--private-report`.
  - The Python `flow()` / `search_feed()` defaults stay the baseline.
- **Drift check at `3a7d0af`, clean tree:** `--verify-baseline baseline-1.json` → `VERIFY OK`, 57/57 identical.
- **Phone:** the test app was re-vendored from `3a7d0af` (test app `22607af`). Its `questionRun.ts` now passes the question context to search, which rank_v1 needs. The flow test was re-exported with the frozen search: 13 cases, results identical to the frozen dev run's flow13.
- **Phase finding (user, 2026-11-16):** false "not found" (the right row shown, the model says not found) is the largest failure pool: 10 answerable dev cases.
  - It was **not fixable by prompt design.** Answer v4's one targeted sentence made it worse: 7 correct answers lost, 0 of 10 targets fixed.
  - The results list mitigates it: in all 10 cases the source row is shown, so the case is still helpful.
  - This is a model-capacity limitation of the 0.6B model. It supports the future-work recommendation (a larger or fine-tuned model, outside this no-training phase).
- **Held-out (user, 2026-11-16):** used at most twice. After the final run, any further improvement is a v2 on a new held-out set (ADR 0007).
- **Next:** the user's held-out final (step 4), then the phone smoke run of flow13 (step 3), then window_v1 (`docs/plans/window-fallback.md`) if approved.
