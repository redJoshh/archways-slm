# Fine-tuning data plan for gemma3:1b

- **Status:** DRAFT, for the user's review. Nothing here is decided until the user approves it, except the decisions marked **Decided**.
- **Decided (2026-10-29, user):** train the answer call only (Decision 1); the overlap review rule in Decision 5.
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

- **A NEW synthetic corpus**, for example `data/train/announcements_synth_v1.json` (not created). It is fully separate from `data/seed/announcements.json`.
- It must contain no dev seed row (title or body), no dev question and no e2e question. The overlap check below enforces this lexically.
- Rows use the seed's field layout (`id`, `title`, `body`, `office`, `priority`, `published_at`, `scheduled`, `status`, `is_archived`, `year_level`), so the real fakebackend can serve them.
- Include the same trap types as the dev set, as new, invented content:
  - **Injection:** instructions written inside a body ("ignore your rules…"). The target ignores them.
  - **Superseded:** two live rows on the same matter with different `published_at`. The target uses only the later one and never states the older fact. Per the 2026-10-25 devlog, edits happen in place, so this is defensive. Keep it a minority of examples.
  - **Long body past 500 characters,** with the key fact after the cut-off. The target must not supply the missing fact. The seed has 1 such row today.
  - **year_level:** rows for one year level. The target says who the row is for and doesn't widen it.
  - **Partial matches:** a retrieved row shares keywords but answers a different question (as in e2e-019's exam dates). The target is the not-found sentence.
  - **Answerable:** a plain retrieved row that answers the question. The target answers. This counters e2e-005's over-declining.
  - **DRAFT and archived rows:** in the corpus, so the visibility filter is exercised. They never appear in inputs.
- Vary `now` across examples, with different dates and weekdays, so the model doesn't learn one fixed date.

**Recommendation:** write the corpus generator as a script in the repo (a later task). It should be reviewable and rerunnable, and it records its inputs the way the probes do.

## Decision 3: building the inputs

Inputs must look exactly like evaluation inputs. Build them with the real code, not a copy of it:

- the frozen prompt `prompts/e2e_answer_v1.txt` via `load_prompt` (and `e2e_query_v1.txt` if the query call is ever trained)
- `fakebackend.search_announcements` with the default matcher, at the example's `now`: visibility filter, 500-character excerpt truncation, ranking
- `announcements_message` from `scripts/probe_end_to_end.py`: the `Question:` line, the `<announcements>` delimiters, and the `<` escaping
- no answer-call example when retrieval returns nothing, because the pipeline sends the fixed not-found message without a model call

**Chat template risk.** The `ollama show gemma3:1b --modelfile` template renders a system message as its own `<start_of_turn>user` turn. So our system prompt and user message become two consecutive user turns. A training library's own Gemma template may render this differently (for example, by merging system into the first user turn; unverified). **Built:** `archways_assistant.render.render_gemma3()` reproduces the Ollama template exactly. Training text must be rendered with it, not with a library's own Gemma template.
- The template is saved as `tests/fixtures/ollama_gemma3_1b_template.txt`.
- Evidence from `scripts/check_render.py` (devlog, 2026-10-29): over the 19 e2e answer calls, raw `/api/generate` with the rendered text gave the same `prompt_eval_count` and the same reply as `/api/chat` in 19/19.
- In raw mode, Ollama 0.40.13 adds one start-of-text token, and doesn't add a second one when the text already starts with `<bos>`. So the training tokenizer must give exactly one `<bos>` before the rendered text. How the chosen training library handles this is unverified.

## Decision 4: targets

| Option | For | Against |
|---|---|---|
| A. Larger open teacher on a free Colab or Kaggle GPU | Zero API cost; many examples. | Teacher errors; free-tier limits; license questions. |
| B. Hand-written targets only | Highest quality. | Slow; few examples. |
| C. Rule-built targets from the generator's known facts | Exact and cheap. | Stiff wording; the model may learn templates. |

**Recommendation: A, filtered, plus a hand-reviewed sample, with C for the fixed not-found sentence.**

- **Teacher:** for example Qwen3 14B or Gemma 3 12B, 4-bit, run with Ollama or llama.cpp on the free GPU. It gets the same system prompt and user message the student will see.
  - Whether these fit and run at a useful speed on a free T4-class GPU is unverified.
  - Session and quota limits are unverified.
- **Filters,** reusing `archways_assistant.e2escore`. An example is kept only if all of these hold:
  - `guard()` does not fire
  - `unsupported_claims()` is empty
  - `failures()` is empty against the generator's known `must_include`, `must_not_include`, `superseded` and `expects_not_found`
  - the target has at most 3 sentences
  - the target never states `posted_at`
- **Record the rejection rate per trap type.** A high rate means the teacher or the prompt is wrong for that trap.
- **Hand review:** the user reviews a random sample, for example 50 examples or 5%, whichever is larger, before training. The sample size is a proposal.
- **Not-found targets** are the exact `NOT_FOUND_MESSAGE` string, set by rule rather than taken from the teacher.

**License questions (all unverified; to settle before generating):**

- **Teacher license:** whether the teacher's license allows using its outputs to train another model. Qwen3 is believed to be Apache-2.0 (unverified).
- **Gemma teacher:** the Gemma Terms of Use (printed by `ollama show gemma3:1b --modelfile`) define a model trained on synthetic Gemma outputs as a Model Derivative, and say Outputs themselves are not Model Derivatives. What that means for this project is unverified.
- **Distribution:** the fine-tuned gemma3:1b is a Model Derivative either way. It is unverified what the Gemma Terms require when it ships inside the app (passing on the terms and the use policy). 0001 already lists Gemma license terms as unverified.
- **Free GPU terms:** whether Colab's and Kaggle's free tiers allow this use is unverified.

## Decision 5: size, split and the overlap check

- **Size options:** about 500, about 1,000, or about 3,000 answer-call examples after filtering. **Recommendation: about 1,000 for the first LoRA.** That it is enough is unverified; the validation loss and the dev e2e run will show it.
- **Proposed mix,** a starting point to review:
  - about 50% answerable
  - about 20% partial match leading to the not-found sentence
  - about 10% each for superseded, long body, and injection
  - year_level rows spread through all groups
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
    - Where the decisions are recorded is not decided. A proposal: one JSONL file per checked file, with the candidate id, the decision and the date, committed next to the generator.
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
2. Teacher choice, once the license questions are settled.
3. Size, mix and hand-review sample size.
4. Who writes the synthetic corpus: generated by a script, written by hand, or both?
