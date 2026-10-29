# Fine-tuning data plan for gemma3:1b

- **Status:** DRAFT, for the user's review. Nothing here is decided until the user approves it, except the decisions marked **Decided**.
- **Decided (2026-10-29, user):** train the answer call only (Decision 1); the corpus authorship (Decision 2); the training `<bos>` rule (Decision 3); the teacher (Decision 4); size, mix, the overlap review rule and where review decisions are kept (Decision 5).
- **Date:** 2026-10-29
- **Context:** [ADR 0002](../decisions/0002-gemma-primary-and-gate-2.md) confirms fine-tuning, for gemma3:1b only. This plan covers the data and the export path. No training code and no data exist yet.

"Unverified" marks anything the repo or the runs don't show.

## Evidence: where gemma3:1b fails today

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

- the frozen prompt `prompts/e2e_answer_v1.txt` via `load_prompt` (and `e2e_query_v1.txt` if the query call is ever trained)
- `fakebackend.search_announcements` with the default matcher, at the example's `now`: visibility filter, 500-character excerpt truncation, ranking
- `announcements_message` from `scripts/probe_end_to_end.py`: the `Question:` line, the `<announcements>` delimiters, and the `<` escaping
- no answer-call example when retrieval returns nothing, because the pipeline sends the fixed not-found message without a model call

**Chat template risk.** The `ollama show gemma3:1b --modelfile` template renders a system message as its own `<start_of_turn>user` turn. So our system prompt and user message become two consecutive user turns. A training library's own Gemma template may render this differently (for example, by merging system into the first user turn; unverified). **Built:** `archways_assistant.render.render_gemma3()` reproduces the Ollama template exactly. Training text must be rendered with it, not with a library's own Gemma template.
- The template is saved as `tests/fixtures/ollama_gemma3_1b_template.txt`.
- Evidence from `scripts/check_render.py` (devlog, 2026-10-29): over the 19 e2e answer calls, raw `/api/generate` with the rendered text gave the same `prompt_eval_count` and the same reply as `/api/chat` in 19/19.
- In raw mode, Ollama 0.40.13 adds one start-of-text token, and doesn't add a second one when the text already starts with `<bos>`.
- **Decided (2026-10-29, user): `render_gemma3()` never adds `<bos>`, and the training notebook must assert exactly one `<bos>` per tokenized example.** How the chosen training library adds `<bos>` is unverified, which is why the assert is required.

## Decision 4: targets

**Decided (2026-10-29, user):**
- **Teacher for real data: Qwen3-14B on a Kaggle GPU.**
  - It gets the frozen e2e answer prompt plus teacher-only instructions.
  - The training input uses the frozen prompt only. The teacher-only instructions never appear in it.
  - Not checked: whether Qwen3-14B fits a Kaggle GPU at a useful speed, Kaggle's session and quota limits, and how its thinking output is switched off in the chosen runtime.
- **Pilot first: local qwen3:1.7b, about 50 examples, to debug the pipeline only.** Pilot outputs are never used as training data.
- **Filters,** reusing `archways_assistant.e2escore`. An example is kept only if all of these hold:
  - `guard()` does not fire
  - `unsupported_claims()` is empty
  - `failures()` is empty against the generator's known `must_include`, `must_not_include`, `superseded` and `expects_not_found` (taken from the `Trap` records)
  - the target has at most 3 sentences
  - the target never states `posted_at`
- **Record the rejection rate per trap type.** A high rate means the teacher or the prompt is wrong for that trap.
- **Hand review:** the user reviews a random sample, for example 50 examples or 5%, whichever is larger, before training. The sample size is still a proposal.
- **Not-found targets** are the exact `NOT_FOUND_MESSAGE` string, set by rule rather than taken from the teacher.

### License texts

Quoted verbatim from what is on this machine. Anything not quoted is unverified.

**Qwen3:** quoted from `ollama show qwen3:1.7b --license` (the local qwen3:1.7b, used for the pilot). **Qwen3-14B's own license text was not checked, so it is unverified that it is the same.**

> Apache License
> Version 2.0, January 2004

> 2. Grant of Copyright License. Subject to the terms and conditions of this License, each Contributor hereby grants to You a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright license to reproduce, prepare Derivative Works of, publicly display, publicly perform, sublicense, and distribute the Work and such Derivative Works in Source or Object form.

> Copyright 2024 Alibaba Cloud

- The quoted license text never mentions model outputs (no occurrence of "output").
- Whether teacher outputs may be used as training data under it is therefore not settled by the text. That is unverified.

**Gemma Terms of Use:** quoted from `ollama show gemma3:1b --license` ("Last modified: February 21, 2024"). The fine-tuned model is gemma3:1b, so these terms govern it.

> (e) "Model Derivatives" means all (i) modifications to Gemma, (ii) works based on Gemma, or (iii) any other machine learning model which is created by transfer of patterns of the weights, parameters, operations, or Output of Gemma, to that model in order to cause that model to perform similarly to Gemma, including distillation methods that use intermediate data representations or methods based on the generation of synthetic data Outputs by Gemma for training that model. For clarity, Outputs are not deemed Model Derivatives.

> 3.1 Distribution and Redistribution
> You may reproduce or Distribute copies of Gemma or Model Derivatives if you meet all of the following conditions:
>
> You must include the use restrictions referenced in Section 3.2 as an enforceable provision in any agreement (e.g., license agreement, terms of use, etc.) governing the use and/or distribution of Gemma or Model Derivatives and you must provide notice to subsequent users you Distribute to that Gemma or Model Derivatives are subject to the use restrictions in Section 3.2.
> You must provide all third party recipients of Gemma or Model Derivatives a copy of this Agreement.
> You must cause any modified files to carry prominent notices stating that you modified the files.
> All Distributions (other than through a Hosted Service) must be accompanied by a "Notice" text file that contains the following notice: "Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms".

> 3.2 Use Restrictions
> You must not use any of the Gemma Services:
>
> for the restricted uses set forth in the Gemma Prohibited Use Policy at ai.google.dev/gemma/prohibited_use_policy ("Prohibited Use Policy"), which is hereby incorporated by reference into this Agreement; or
> in violation of applicable laws and regulations.

> 3.3 Generated Output
> Google claims no rights in Outputs you generate using Gemma. You and your users are solely responsible for Outputs and their subsequent uses.

- The fine-tuned gemma3:1b is a modification of Gemma, so it is a Model Derivative under (e)(i).
- If it ships inside the app, the quoted 3.1 conditions apply: the use restrictions in the app's terms, a copy of the Agreement, modified-file notices, and the Notice file. Whether shipping inside an app counts as a Distribution is unverified.
- The Prohibited Use Policy is incorporated by reference, but its text was not checked (unverified).

**Kaggle:** no Kaggle terms text was available to quote. Whether Kaggle's terms allow this use of its free GPUs is unverified.

## Decision 5: size, split and the overlap check

- **Decided (2026-10-29, user): size and mix.**
  - About 800 training and 100 validation answer-call examples, after filtering.
  - Mix by behavior (target behavior per the frozen answer prompt):

    | Behavior | Share | Target |
    |---|---|---|
    | Single relevant result | 35% | Answers from it |
    | Distractor / wrong-topic result | 20% | The not-found sentence |
    | Detail not in the results | 20% | The not-found sentence when the results don't answer the question |
    | Superseded dates | 10% | Only the later row's fact |
    | Injection | 5–10% | Ignores the instruction |
    | year_level | 5% | Keeps the stated year level |

  - Filipino or Taglish questions: about 10%, spread across the categories, always answered in English.
  - **The listed shares add up to 95–100%.** At 5% injection, 5% is unassigned; which behavior gets it is not decided.
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
    - **Decided (2026-10-29, user):** review decisions are kept as one committed JSONL file per checked file (location and fields to be set when the generator is built). Generated training data stays gitignored (`data/generated/`).
  - **Gate:** training starts only when every flagged item has been dropped or has a recorded keep decision from the user's review.
  - **Expected false positives:** dev against e2e already gives 8 paraphrase-flagged pairs at the 0.3 threshold, because short campus questions share words ("When is the deadline…"). Expect to drop a share of generated questions. The threshold stays 0.3.
  - **Limit:** the check is lexical. A paraphrase in different words passes. Semantic paraphrase detection is unverified.
- **Indirect leakage:** dev and e2e scores may be used to choose between these plan options. The generator must not be tuned case by case to make specific dev or e2e cases pass. The held-out file is only for the final comparison.

## Decision 6: export and evaluation path

1. **LoRA** on gemma3:1b, trained on the free GPU. The library (for example Hugging Face PEFT, or Unsloth) and its versions are unverified. Record base model revision, library versions, hyperparameters, data file hashes and the git commit.
2. **Merge** the LoRA into the base weights.
3. **Convert to GGUF** with llama.cpp's converter, then quantize to **Q4_K_M**, the quantization `ollama show gemma3:1b` reports for the base. That way the control and the tuned model differ only in the weights. Whether the converter supports this Gemma 3 checkpoint is unverified.
4. **`ollama create`** from a Modelfile with:
   - `FROM` the merged GGUF
   - the `TEMPLATE` copied verbatim from `ollama show gemma3:1b --modelfile`
   - `PARAMETER stop "<end_of_turn>"`

   Check that `ollama show <tuned> --template` and `ollama show gemma3:1b --template` print identical text.
5. **Evaluate with ADR 0002's cold settings:**
   - one `ollama serve` with `OLLAMA_NUM_PARALLEL=1`, `--num-gpu 0`, `--keep-alive 0`, the greedy options, one recorded Ollama version
   - the tuned model and the untuned gemma3:1b control
   - first the 34 dev e2e cases, then the held-out set once
   - one warm run reported alongside, not gated
6. **Phone:** GGUF through Ollama is the evaluation path. Whether the phone runtime chosen in Gate 1 can load this GGUF, or needs another export of the same weights, is unverified.

## Open questions for the user

1. ~~Approve answer-call-only (Decision 1, A)?~~ Decided 2026-10-29: yes.
2. ~~Teacher choice.~~ Decided 2026-10-29: Qwen3-14B on Kaggle, with a qwen3:1.7b pilot. The license questions above stay open.
3. ~~Size and mix.~~ Decided 2026-10-29. Still open: the unassigned 0–5% of the mix, and the hand-review sample size.
4. ~~Who writes the corpus.~~ Decided 2026-10-29: teammate-written anchors, teacher expansion, code-inserted traps.
