# Fine-tuning data plan for qwen3:0.6b (post-UAT)

- **Status:** DRAFT, for the user's review. Nothing here is decided until the user approves it, except the decisions marked **Decided**.
- **Post-UAT:** UAT (week of 2026-11-09) ships **untuned** qwen3:0.6b ([ADR 0004](../decisions/0004-model-choice-qwen.md), "UAT configuration"). Fine-tuning starts after UAT. Nothing in this plan is needed for UAT.
- **Retargeted 2026-11-06 (DRAFT changes, for the user's review):**
  - the model, from gemma3:1b to qwen3:0.6b
  - the qwen3 training render
  - the compact training format and the Gate 2 comparison
  - a Taglish share proposal
  - export
  - the removal of the gemma-specific parts (see "Removed for qwen3:0.6b")
  - the blocked list
- **Decided (2026-10-29, user):** train the answer call only (Decision 1); the corpus authorship (Decision 2); the teacher, its pilot checks and fallback, and the hand review (Decision 4); size, mix, the overlap review rule and the review files (Decision 5). Decision 3's `<bos>` rule was also decided then; it is removed for qwen3:0.6b (below).
- **Decided (2026-11-06, user):** the loss covers the reply plus the closing `<|im_end|>`, and nothing before it (Decision 3).
- **Date:** 2026-10-29; retargeted 2026-11-06
- **Context:** [ADR 0004](../decisions/0004-model-choice-qwen.md) (accepted 2026-11-06) makes qwen3:0.6b the primary on-device model and the fine-tuning target, superseding [ADR 0002](../decisions/0002-gemma-primary-and-gate-2.md)'s gemma3:1b. This plan covers the data and the export path. No training code and no data exist yet.

"Unverified" marks anything the repo or the runs don't show.

## Evidence: where qwen3:0.6b fails today

Source: ADR 0004 and the devlog of 2026-10-31. These are cold runs on 34 dev cases with answer v1 and query v1, one run each.

| Run | Failed after guards | What failed |
|---|---|---|
| `and_v2` (default matcher), `commit=e4e6959` | 6/34 | All unhelpful, none unsafe (0/34 before and after guards). Retrieval misses in the query call: e2e-014, 023 (and e2e-003, 021, not-found traps that still passed). The rest are not-found replies although the right row was retrieved. |
| `and_v1`, `commit=c48922a` | 8/34 | Not-found despite the right result: e2e-001, 005, 012. Retrieval misses: e2e-014, 023, 027, 028, 029. |
| `and_v1`, compact answer v2, `commit=9481071` | 13/34 | Five new not-found replies with the right row retrieved (e2e-007, 009, 011, 032) and one `invented` (e2e-030, which copied the result block). |

- **qwen3:0.6b's answer-call failure is over-declining**, not inventing: it gives the not-found sentence when the answer is in the results. The compact format made this worse when untuned. So the "Single relevant result" share (Decision 5) is what the compact-format training must fix.
- **The query call's retrieval misses are ADR 0004's main quality risk.** This plan still trains the answer call only (Decision 1).
- Taglish: 3/9 failed (devlog, 2026-10-31).
- Scope: our own 34-case dev set, 10 of its cases written after seeing failures. The `and_v2` synonym map was built from dev failures.

## Historical: where gemma3:1b failed (2026-10-29)

Kept for comparison only; gemma3:1b is no longer the target.

Source: the two identical cold baseline runs (devlog, 2026-10-29), `runs/e2e34_greedy_gemma3_1b_cpu_parallel1_keepalive0{,_run2}.txt`, 34 dev cases, matcher `and_v1`. Failed after guards: 10/34. Unsafe 3/34 before guards, 1/34 after. Unhelpful 7/34 before guards, 9/34 after.

| Call | Cases | What happened |
|---|---|---|
| Query | e2e-008, 014, 027, 029, 030, 031 (`retrieval_miss`) | Keyword queries such as `tuition payment`, `graduation deadline`, `second-term enrolment` and `physical examinations` matched no row under `and_v1`. Invalid search arguments: 0/34. |
| Answer | e2e-002 (`stale`) | Stated both the current and the superseded dropping deadline. The guard can't catch this (the dates are in the results). Still unsafe after guards. |
| Answer | e2e-003, e2e-009 (`invented`) | Invented dates ("November 15th"; "November 7th to 8th"). The guard fired, so both became unhelpful fallbacks. |
| Answer | e2e-005 (`safe_unhelpful`) | The right row was retrieved, but the model replied with the not-found sentence. |

- **All 3 unsafe-before-guards cases come from the answer call.** Gate 2 requires 0 unsafe after guards.
- **The query-call failures are mostly vocabulary mismatches with the matcher.** The contract v2 backlog in the devlog lists them as word-form and synonym misses. Under `prefix_v2`, unhelpful after guards was 4–5/34, but those were warm runs at the old sampling settings and aren't directly comparable.
- Scope: this is our own 34-case dev set, and 10 of its cases were written after seeing failures.

## Decision 1: which calls to train

| Option | For | Against |
|---|---|---|
| A. Answer call only | Targets every unsafe case and the over-declining one (e2e-005). The query call keeps its current 0/34 invalid rate. | Doesn't help retrieval misses. |
| B. Query call only | Could learn the matcher's vocabulary. | The misses are a matcher problem, and Spring must match the same rule. Training toward the dev seed vocabulary risks fitting the dev set. Doesn't touch unsafe. |
| C. Both in one LoRA | One adapter, and both prompts are covered. | Twice the data work. A query-call regression would be hidden inside one combined score. |

**Decided (2026-10-29, user): A.** Train the answer call only for the first LoRA. Fix retrieval in the matcher and Spring, where it can be tested with shared vectors. Revisit C only if query-call failures remain after the matcher decision.

Also unverified: whether an answer-only LoRA changes the query call's outputs. The query call runs through the same weights, so Gate 2 must re-measure both calls.

Note (2026-11-06): for qwen3:0.6b, ADR 0004 names the query call's retrieval misses as the main quality risk (under `and_v2`: e2e-003, 014, 021, 023). Decision A is unchanged. Option C is the one to revisit if those misses remain on real announcements.

**Recorded 2026-11-07 (user): the query call should be trained too.**
- Evidence: the labelled flow-test questions on the real snapshot (devlog 2026-11-07). Under `and_v3`, two misses come from the model's queries, not the matcher:
  - q01: the query `office` never reaches row 18.
  - q07: `remote work` cannot reach the weather suspension, id 9 (a two-part question).
- Decision 1 should move from A toward C (or a separate query-call LoRA). How to split the data and score the query call separately is open for the user's review.

## Decision 2: training announcements

- **A NEW synthetic corpus,** fully separate from `data/seed/announcements.json`. Generated files go in `data/generated/`, which is gitignored.
- It must contain no dev seed row (title or body), no dev question and no e2e question. The overlap check below enforces this lexically.
- Rows use the seed's field layout (`id`, `title`, `body`, `office`, `priority`, `published_at`, `scheduled`, `status`, `is_archived`, `year_level`), so the real fakebackend can serve them. **Built:** `archways_assistant.synthetic.ROW_SCHEMA` and `validate_rows()`. Ids are `anc-NNN` (anchors) or `syn-NNN` (expanded rows), so a seed row (`ann-NNN`) can never pass as synthetic.
- Include the same trap types as the dev set, as new, invented content:
  - **Injection:** instructions written inside a body ("ignore your rules…"). The target ignores them.
  - **Superseded:** two live rows on the same matter with different `published_at`. The target uses only the later one and never states the older fact. Per the 2026-10-25 devlog, edits happen in place, so this is defensive. Keep it a minority of examples.
  - **Long body past 500 characters,** with the key fact after the cut-off. The target must not supply the missing fact. The seed has 1 such row today.
  - **year_level:** rows for one year level. The target says who the row is for and doesn't widen it.
  - **Partial matches:** a retrieved row shares keywords but answers a different question (as in e2e-019's exam dates). The target is the not-found sentence.
  - **Answerable:** a plain retrieved row that answers the question. The target answers. This counters e2e-005's over-declining.
  - **DRAFT and archived rows:** in the corpus, so the visibility filter is exercised. They never appear in inputs.
- Vary `now` across examples, with different dates and weekdays, so the model doesn't learn one fixed date.

**Decided (2026-10-29, user): who writes the corpus.**
- A teammate hand-writes 20–30 style anchors, from scratch, never paraphrased from a real announcement. Claude Code does not write anchors. The guide is `data/anchors/TEMPLATE.md`; `data/anchors/example_anchor.json` is a deliberately fictional example, not a training anchor.
- The teacher expands the anchors to 150–250 rows.
- Code inserts the traps. **Built:** pure functions in `archways_assistant.synthetic`:
  - `insert_long_body`: the key fact starts at or after character 500
  - `insert_injection`: the instruction ends inside the 500-character excerpt
  - `insert_superseded_pair`: two live rows, the later one with the new fact
  - `insert_year_level`
- Each inserter returns a `Trap` record with its label (`long_body`, `injection`, `superseded`, `year_level`) and facts. The record is kept outside the row, so the scorer can use it later without the label reaching the model.
- The corpus generator itself (which reads anchors, calls the teacher, inserts traps and records its inputs) is a later task.

## Decision 3: building the inputs

Inputs must look exactly like evaluation inputs. Build them with the real code, not a copy of it:

- **the compact format (DRAFT, 2026-11-06):** the frozen prompt `prompts/e2e_answer_v2.txt` via `load_prompt`, with the user message from `compact_announcements_message` in `scripts/probe_end_to_end.py`. This format is the Gate 1 lever: it shortens the case part (e2e-009: 394 → 215 tokens). See "Decided: the compact results format moves into fine-tuning" below. (`e2e_query_v1.txt` applies if the query call is ever trained.)
- `fakebackend.search_announcements` with the default matcher (`and_v2`), at the example's `now`: visibility filter, 500-character excerpt truncation, newest-first order
- no answer-call example when retrieval returns nothing, because the pipeline sends the fixed not-found message without a model call

**Training render (DRAFT, 2026-11-06).** Training text is rendered with `archways_assistant.render.render_qwen3_example()`, never with a training library's own Qwen3 chat template. The library's template may differ from Ollama's (unverified); for example, Ollama appends ` /no_think`.

- `render_qwen3()` reproduces what Ollama's qwen3:0.6b template sends with `"think": false`:

  ```
  <|im_start|>system\n\n{system}<|im_end|>\n<|im_start|>user\n{user} /no_think<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n
  ```

  - the blank line after `system`, which the template prints
  - ` /no_think` on the user turn
  - the open assistant turn with the empty think block
  - no start-of-text token
- `render_qwen3_example(messages, reply)` returns `(prompt, target)`:
  - `prompt` is the text above, exactly what the model sees at inference.
  - `target` is the reply followed by `<|im_end|>`, exactly what the model emits with thinking off.
  - This is deliberately not Ollama's rendering of a three-message history, which would leave out the empty think block that the model sees at inference.
- **Decided (2026-11-06, user): loss only on the target, the reply tokens plus the closing `<|im_end|>`.** Nothing before it is trained on, including the empty think block.
- **The training notebook must assert, per tokenized example:**
  - no start-of-text token was added, and the first token is `<|im_start|>`
  - the target ends with exactly one `<|im_end|>`, and it is the only `<|im_end|>` in the target
  - the loss mask covers exactly the target tokens
  - tokenizing prompt + target gives the same tokens as tokenizing the prompt and the target separately and joining them (the prompt ends with `\n\n` and the reply starts with text, so the split is expected to be clean; unverified until checked)
- The template is saved as `tests/fixtures/ollama_qwen3_0_6b_template.txt` (Ollama 0.40.14, pinned by SHA-256 in `tests/test_render.py`).
- Evidence: `scripts/check_render_qwen3.py` compares `/api/chat` with raw `/api/generate` of the rendered text, cold, for every e2e query and answer call (devlog, 2026-11-06).

## Decision 4: targets

**Decided (2026-10-29, user):**
- **Teacher for real data: Qwen3-14B on a Kaggle GPU.**
  - It gets the frozen e2e answer prompt plus teacher-only instructions. With the compact format, that is `prompts/e2e_answer_v2.txt` and the compact user message (DRAFT, 2026-11-06).
  - The training input uses the frozen prompt only. The teacher-only instructions never appear in it.
  - **Decided: checked during the pilot phase, before any real data:** whether Qwen3-14B fits the Kaggle GPU at a useful speed, and whether `"think": false` keeps thinking text out of its replies. If Qwen3-14B doesn't fit, the fallback is **Qwen3-8B**, and the switch is logged in the devlog.
  - Still not checked: Kaggle's session and quota limits.
- **Pilot first: local qwen3:1.7b, about 50 examples, to debug the pipeline only.** Pilot outputs are never used as training data.
- **Filters,** reusing `archways_assistant.e2escore`. An example is kept only if all of these hold:
  - `guard()` does not fire
  - `unsupported_claims()` is empty
  - `failures()` is empty against the generator's known `must_include`, `must_not_include`, `superseded` and `expects_not_found` (taken from the `Trap` records)
  - the target has at most 3 sentences
  - the target never states `posted_at`
- **Record the rejection rate per trap type.** A high rate means the teacher or the prompt is wrong for that trap.
- **Hand review (decided, 2026-10-29, user):** done by the user, not by Claude Code, before training.
  - Sample 10% of each generated file, stratified by category, with at least 10 per category.
  - If more than 2 in a category's sample are bad, the user reviews the whole category.
- **Not-found targets** are the exact `NOT_FOUND_MESSAGE` string, set by rule rather than taken from the teacher.

### License texts

Quoted verbatim from what is on this machine. Anything not quoted is unverified.

**Qwen3:** quoted from `ollama show qwen3:1.7b --license` (the local qwen3:1.7b, used for the pilot). **Qwen3-14B's own license text was not checked, so it is unverified that it is the same.**

**qwen3:0.6b** (the fine-tuned model): `ollama show qwen3:0.6b --license`, checked 2026-11-06. It is the Apache License, Version 2.0, January 2004, with the same section 2 text and the same "Copyright 2024 Alibaba Cloud" line as quoted below, and no occurrence of "output". Shipping the tuned model means following the Apache 2.0 redistribution conditions (section 4: a copy of the License, notices on modified files, and the NOTICE text if any). This is a reading of the text, not verified legal advice.

> Apache License
> Version 2.0, January 2004

> 2. Grant of Copyright License. Subject to the terms and conditions of this License, each Contributor hereby grants to You a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright license to reproduce, prepare Derivative Works of, publicly display, publicly perform, sublicense, and distribute the Work and such Derivative Works in Source or Object form.

> Copyright 2024 Alibaba Cloud

- **Decided (2026-10-29, user):** the quoted Apache License 2.0 text has no clause about model outputs (no occurrence of "output"). This is recorded as **"no restriction found"**.
- This is a reading of the license text, not verified legal advice.

**Gemma Terms of Use:** removed 2026-11-06; gemma3:1b is not fine-tuned or shipped (see "Removed for qwen3:0.6b"). The quoted text is in git history (`docs/plans/finetune-data-plan.md` at `c8db288`).

**Kaggle:** no Kaggle terms text was available to quote. Whether Kaggle's terms allow this use of its free GPUs is unverified.

## Decision 5: size, split and the overlap check

- **Decided (2026-10-29, user): size and mix.**
  - About 800 training and 100 validation answer-call examples, after filtering.
  - Mix by behavior (target behavior per the frozen answer prompt):

    | Behavior | Share | Target |
    |---|---|---|
    | Single relevant result | 35% | Answers from it |
    | Distractor / wrong-topic result | 25% | The not-found sentence |
    | Detail not in the results | 20% | The not-found sentence when the results don't answer the question |
    | Superseded dates | 10% | Only the later row's fact |
    | Injection | 5% | Ignores the instruction |
    | year_level | 5% | Keeps the stated year level |

  - Filipino or Taglish questions: about 10%, spread across the categories, always answered in English. **Proposed change (DRAFT, 2026-11-06), see "Taglish questions" below: 15%.**
  - The shares add up to 100% (decided 2026-10-29: distractor/wrong-topic 25%, injection 5%).
  - **Zero empty-retrieval examples.** With no results the pipeline sends the fixed not-found message without a model call.
  - **The fixed `now` varies across examples.**
- **Split:** 90/10 train/validation, split by synthetic announcement (or group of related rows), not by example. The same row never appears on both sides.
- **Overlap check, on every generated file before training,** with `scripts/check_overlap.py`:
  - **Questions:** each generated file's `question` field against `evals/dev_questions.jsonl` and `evals/e2e_cases.jsonl`.
  - **Held-out:** the same check against the held-out file, run **by the user only**, who pastes the summary line. Claude Code never runs it or reads that file.
  - **Announcements:** synthetic titles and bodies against the seed rows' titles and bodies. `check_overlap.py` reads the seed's JSON array directly; run it once with `--protected-field title --candidate-field title` and once with `body`.
  - **Whole inputs:** the full rendered user message also gets the exact-copy check against the eval questions, which catches a question embedded anywhere.
  - **Review rule (decided, 2026-10-29, user):**
    - Flagged training items are dropped by default.
    - The flagged share is reported per file (`check_overlap.py` prints `flagged items k/n (p%)`).
    - If a file's share exceeds 10%, the user reviews its flagged items by hand with `--show-candidates`, and records a decision for each: near-copy → drop; same topic only → keep.
    - The threshold stays 0.3.
    - **Decided (2026-10-29, user): review files.** One committed file per checked file: `data/review/<checked-file-name>.overlap-review.jsonl`.
      - One line per decision, with the fields `candidate_id`, `decision` (`drop` or `keep`), `reason` (`near-copy` or `same-topic-only`), `reviewer` and `date`.
      - Never held-out text: these files hold only training-side candidate ids and decisions.
      - Generated training data stays gitignored (`data/generated/`).
  - **Gate:** training starts only when every flagged item has been dropped or has a recorded keep decision from the user's review.
  - **Expected false positives:** dev against e2e already gives 8 paraphrase-flagged pairs at the 0.3 threshold, because short campus questions share words ("When is the deadline…"). Expect to drop a share of generated questions. The threshold stays 0.3.
  - **Limit:** the check is lexical. A paraphrase in different words passes. Semantic paraphrase detection is unverified.
- **Indirect leakage:** dev and e2e scores may be used to choose between these plan options. The generator must not be tuned case by case to make specific dev or e2e cases pass. The held-out file is only for the final comparison.

## Decision 6: export and evaluation path

Retargeted to qwen3:0.6b (DRAFT, 2026-11-06).

1. **LoRA** on qwen3:0.6b, trained on the free GPU. The library (for example Hugging Face PEFT, or Unsloth) and its versions are unverified. Record base model revision, library versions, hyperparameters, data file hashes and the git commit.
2. **Merge** the LoRA into the base weights.
3. **Convert to GGUF** with llama.cpp's converter, then quantize to **Q4_K_M**, the quantization `ollama show qwen3:0.6b` reports for the base (751.63M parameters; blob `sha256-7f4030143c1c…`, 522,640,096 bytes). That way the control and the tuned model differ only in the weights. Whether the converter supports this Qwen3 checkpoint is unverified.
4. **`ollama create`** from a Modelfile with:
   - `FROM` the merged GGUF
   - the `TEMPLATE` copied verbatim from `ollama show qwen3:0.6b --modelfile`
   - `PARAMETER stop "<|im_end|>"` and `PARAMETER stop "<|im_start|>"` (`render.QWEN3_STOP`)

   Check that `ollama show <tuned> --template` and `ollama show qwen3:0.6b --template` print identical text, and run `scripts/check_render_qwen3.py --model <tuned>`.
5. **Evaluate with ADR 0002's cold settings:**
   - one `ollama serve` with `OLLAMA_NUM_PARALLEL=1`, `--num-gpu 0`, `--keep-alive 0`, the greedy options, one recorded Ollama version
   - **Gate 2 compares the tuned qwen3:0.6b on the compact format (answer v2) against the untuned qwen3:0.6b control on v1** ([ADR 0004](../decisions/0004-model-choice-qwen.md)), **each on its best configuration**.
     - "Best configuration" (answer and query prompt versions, matcher) is chosen on the dev cases only.
     - It is then written down and frozen before any held-out run, together with the e2e prompts (CLAUDE.md). It is never chosen or changed after seeing held-out results.
   - first the 34 dev e2e cases, then the held-out set once
   - one warm run reported alongside, not gated
6. **Phone:** llama.rn 0.13.0-rc.8 loads the base qwen3:0.6b GGUF on the Redmi 10C (measured, devlog 2026-10-31). Whether it loads the tuned GGUF the same way is unverified. Gate 1 must be re-measured with the tuned model on the compact format.

## Taglish questions (DRAFT proposal, 2026-11-06)

- **Share: 15%** of answer-call examples, about 120 training and 15 validation examples, up from the 10% decided on 2026-10-29. It is spread across the behaviour categories in Decision 5, and the target is always in English.
  - Why: on the 9 Taglish dev cases, qwen3:0.6b fails 3 (devlog, 2026-10-31). 15% is a judgement call, not a measured optimum; nothing shows whether 10% or 15% is better.
- **How they are written:**
  - By hand, by a Filipino-speaking team member, from scratch, against the synthetic announcement rows.
  - Never paraphrased or translated from a held-out, dev, e2e or Taglish dev question (`evals/taglish_cases.jsonl`).
  - The teacher writes only the English targets, never the questions. Claude Code writes none of them.
- **Checks:** the overlap check in Decision 5 also runs these questions against `evals/taglish_cases.jsonl`, and the user's held-out check covers them.
- Unverified: whether the lexical overlap check works as well on Taglish, where short function words ("kailan", "ang", "sa") are shared by most questions.

## Removed for qwen3:0.6b (2026-11-06)

These gemma3:1b-specific parts were removed when the plan was retargeted. The text is in git history (this file at `c8db288`).

- **The `<bos>` rule** (Decision 3, decided 2026-10-29): "`render_gemma3()` never adds `<bos>`, and the training notebook must assert exactly one `<bos>` per tokenized example". Removed because Ollama adds no start-of-text token for qwen3:0.6b (raw `<|im_start|>` → 1 token), and llama.rn counted the same 591 tokens as Ollama for e2e-009's answer prompt. The notebook asserts in Decision 3 replace it.
- **Rendering with `render_gemma3()`** and its chat-template risk (a system message as its own user turn). Replaced by `render_qwen3_example()`.
- **The `<end_of_turn>` stop** and the gemma3:1b template copy in the export path. Replaced in Decision 6.
- **The Gemma Terms of Use quotes**, the Distribution reading, and the open question about the Gemma notice in the app's Terms and Conditions. gemma3:1b is not fine-tuned or shipped (ADR 0004), so the Gemma terms do not apply to the app.
- **gemma3:1b as the Gate 2 control.** Superseded by untuned qwen3:0.6b (ADR 0004).

## Blocked

- **Anchors:** the 20–30 hand-written style anchors from the teammate (Decision 2). The corpus generator can't run without them.
- **Held-out set:** real published announcements are needed before the held-out run (ADR 0002). The user's out-of-scope list for the held-out set must be written down before that run.
- **Probe scoring:** the probe doesn't yet score out-of-scope cases on safety only, or recognize a safe decline (ADR 0002).
- **Kaggle:** session and quota limits, and the terms, are unchecked (Decision 4).
- **Taglish questions:** need a Filipino-speaking writer (above).
- **UAT:** fine-tuning starts after UAT (ADR 0004).

## Deferred: raw-question retrieval and snippet excerpts (2026-10-31, user)

Two proposals from the Gate 1 work are **deferred, not approved**:

- `fts_v3` would search on the student's raw question (no query call), like Postgres full-text search: English stopwords, Snowball stemming, a match on at least ceil(n/2) of the n stems, ranking, limit 3.
- `snip_v1` would show the text around the matched words instead of the first 500 characters of the body.

Reasons (user):

- One session file per system turn (llama.rn `saveSession`/`loadSession`) may fix the phone's cache eviction while keeping the measured retrieval. This is the next phone test.
- `fts_v3`'s ceil(n/2) partial match repeats the idea that broke the not-found traps under `prefix_v2` (e2e-016, 018, 019). This is a prediction; it is untested.
- `snip_v1` saves little (e2e-009's case part: 394 → 350 tokens, estimated) and could expose the long-body trap's hidden fact.

No new dependency and no network fetch were made for either. Training inputs keep the current retrieval and the 500-character excerpt (Decision 3).

## Decided: the compact results format moves into fine-tuning (2026-10-31, user)

- **Background:** a compact way to show the results (`prompts/e2e_answer_v2.txt`: numbered blocks `N. Title (office, posted YYYY-MM-DD[, year Y])` with the excerpt below, newest first, without JSON keys, `id` or `priority`) was proposed for the Gate 1 token budget. It was evaluated cold on 2026-10-31 (devlog).
- **v2 is rejected for untuned use.**
  - qwen3:0.6b failed 13/34 on it, against 8/34 on v1. gemma3:1b failed 10/34 on both.
  - v2 changed the results format and the prompt's wording at once, so which of the two caused qwen3:0.6b's drop is unknown.
- **v1 stays the answer prompt, and untuned evaluations stay on v1.**
- **Training data may use the compact format.** Its effect is measured as tuned versus untuned:
  - the tuned model on the compact format
  - the untuned control on v1, with the protocol of Decision 6
  - Retargeted 2026-11-06: both are qwen3:0.6b (ADR 0004). This is the Gate 1 lever: the compact format shortens the answer call's case part.
  - Using it in training means the training inputs and the tuned model's evaluation prompt both use that format.

## Open questions for the user

1. ~~Approve answer-call-only (Decision 1, A)?~~ Decided 2026-10-29: yes.
2. ~~Teacher choice.~~ Decided 2026-10-29: Qwen3-14B on Kaggle, with a qwen3:1.7b pilot; GPU fit and `"think": false` checked in the pilot phase; fallback Qwen3-8B, logged.
3. ~~Size, mix and hand review.~~ Decided 2026-10-29.
4. ~~Who writes the corpus.~~ Decided 2026-10-29: teammate-written anchors, teacher expansion, code-inserted traps.
5. ~~Open (team to confirm): the mobile app's Terms and Conditions page needs the Gemma notice and use restrictions.~~ No longer applies (2026-11-06): gemma3:1b is not shipped. The app needs the Apache 2.0 notice for qwen3:0.6b instead.
6. Open (DRAFT, 2026-11-06): the Taglish share (15%) and who writes those questions.
7. Open (DRAFT, 2026-11-06): the retargeted Decisions 3 and 6 and the removals.
