# 0004: qwen3:0.6b as the primary model

- **Status:** ACCEPTED (team decision, 2026-11-06). The section "Fallback if Gate 1 is not met" is still OPEN.
- **Date:** proposed 2026-10-31; accepted 2026-11-06
- **Supersedes:** these parts of [0002](0002-gemma-primary-and-gate-2.md):
  - "gemma3:1b is the primary model"
  - "fine-tuning is confirmed, for gemma3:1b only"
  - the Gate 2 control: **it becomes untuned qwen3:0.6b**, evaluated with the same prompts and settings as the tuned model, in place of untuned gemma3:1b
  - qwen3:0.6b as the untuned fallback
- **Still applies:** Gate 2's metrics and protocol in 0002, and Gate 1 in [0001](0001-model-choice.md) with its pass bar in [0003](0003-gate-1-pass-bar.md) and the cold definition in [0005](0005-gate-1-cold-definition.md).

## Context

- 0002 made gemma3:1b the primary model and the fine-tuning target. It did so before any phone measurement.
- 0003 set the Gate 1 bar on the Redmi 10C: a whole question (query call, search and answer call) in under 15 s, and a first model load under 10 s. Both models have now been measured on that phone.
- Evidence: the devlog entries of 2026-10-29 to 2026-10-31. Run files are in `runs/` (gitignored).

## Evidence

### Cold dev baselines (34 e2e cases, `and_v1`, answer prompt v1)

ADR 0002's cold settings: one `ollama serve` with `OLLAMA_NUM_PARALLEL=1`, `--num-gpu 0`, `--keep-alive 0`, greedy options, Ollama 0.40.13.

| | qwen3:0.6b | gemma3:1b |
|---|---|---|
| Runs | 1 (`commit=c48922a`) | 2, identical summaries (`commit=777ad51`, `13ffdb7`) |
| Failed after guards | 8/34 | 10/34 |
| Unsafe before / after guards | 0/34 / 0/34 | 3/34 / 1/34 |
| Unhelpful before / after guards | 8/34 / 8/34 | 7/34 / 9/34 |
| Retrieval hit | 27/34 (20/24 original, 7/10 regression set) | 28/34 (22/24 original, 6/10 regression set) |
| Retrieval misses | e2e-003, 014, 021, 023, 027, 028, 029 | e2e-008, 014, 027, 029, 030, 031 |
| e2e-002 (superseded dates) | PASS | FAIL, stale (gives the old November 6 as well) |

- qwen3:0.6b's failures are all unhelpful: three not-found replies despite the right result (e2e-001, 005, 012) and five retrieval misses. gemma3:1b's include one unsafe reply after the guards (e2e-002, stale).
- On the compact answer prompt v2 (devlog, 2026-10-31), qwen3:0.6b got worse (13/34 failed, five new not-found replies) and gemma3:1b did not (10/34). v2 is rejected for untuned use, so these figures use v1. v2 changed the results format and the prompt's wording at once, so the cause of qwen3:0.6b's drop is unknown. It does show that qwen3:0.6b's results moved more than gemma3:1b's under that change.

### Taglish smoke test (9 scored cases, answer v1, query v1, `and_v1`, cold)

- On 9 Filipino/Taglish dev cases (`evals/taglish_cases.jsonl`, written by the user), qwen3:0.6b and gemma3:1b both failed 3. This is a smoke test only: nine cases, one run each (devlog, 2026-10-31).
- **Under `and_v2`: no improvement for either model** (both still fail 3).
  - gemma3:1b's taglish-04 miss is tied to keeping "may" in its query ("klase kapag may bagyo"). "may" is not a stopword, by decision.
  - qwen3:0.6b's taglish-04 miss comes from a truncated query word ("kailan sinusus").

### Cold dev results under `and_v2` (search contract v2, now the default matcher)

Same settings as the baselines above: answer v1, query v1, one cold run each, `commit=e4e6959` (devlog, 2026-10-31). Scored with the current scorer: the stale-check fix and the wrong-row rule on every case.

| | qwen3:0.6b | gemma3:1b |
|---|---|---|
| Failed after guards | 6/34 | 5/34 |
| Unsafe before / after guards | 0/34 / 0/34 | 3/34 / 1/34 |
| Unhelpful before / after guards | 6/34 / 6/34 | 2/34 / 4/34 |
| Retrieval hit | 30/34 | 33/34 |
| Trap retrieval (10 not-found cases) | 8/10 | 10/10 |

- **gemma3:1b fails 5 and qwen3:0.6b fails 6** (unsafe after guards: 1 vs 0). A difference of one case in 34 is within noise, so the dev set does not separate the two models.
- **The case for qwen3:0.6b now rests mainly on Redmi 10C speed:** the e2e-009 answer call took about 24–26 s on qwen3:0.6b against about 40–43 s on gemma3:1b (below). It no longer rests on dev-set quality.
- The `and_v2` synonym map was built from dev-set failures, so both models' gains overstate held-out gains.

### Redmi 10C (4 GB RAM), llama.rn 0.13.0-rc.8, CPU, development build

| | qwen3:0.6b | gemma3:1b |
|---|---|---|
| e2e-009 answer call, cold | 23.9–25.9 s (591 prompt tokens) | 39.5–43.2 s (631 prompt tokens) |
| Prompt speed | 26.7–29.3 tokens/s | 17.1–18.5 tokens/s |
| Query call, cold | 9.0 s (239 tokens) | not timed |
| Model load | 2.0–2.5 s; 1.0–1.3 s once the file is cached | 4.9 s first; 1.3 s once the file is cached |

- With a cached prefix, qwen3:0.6b's e2e-004 answer call took 9.3 s. Its query call evicts that cache today; one session file per system turn is the next phone test.
- Neither model passes Gate 1.

### Phone memory (`dumpsys meminfo`, app on screen)

| | qwen3:0.6b | gemma3:1b |
|---|---|---|
| TOTAL PSS | 1,039,611 kB (after the third of three cold runs) | 494,672 kB (after one cold run) |
| RSS | 711,444 kB | 173,248 kB |
| Swap PSS | 382,646 kB | 365,648 kB |

- The smaller model shows about twice the PSS. Why is unverified, and the two snapshots were taken in different situations (after three reloads, and after one run). **Memory does not favour qwen3:0.6b on current evidence.**

### Reply stability on e2e-009 (greedy)

- **gemma3:1b:** four different replies from the same prompt: cold Ollama, Nothing Phone 3a Pro cold, Redmi cold (default and 4 threads), and Redmi warm. Redmi with 8 threads matched cold Ollama.
- **qwen3:0.6b:** one reply everywhere it was run: cold Ollama (several runs and both `/api/chat` and raw), and every Redmi run (three cold runs and the cache sequences). It was tested on one phone only.

### Licence (context, not legal advice)

- qwen3 models: Apache License 2.0; the quoted text has no output clause ("no restriction found", data plan).
- gemma3:1b: the Gemma Terms of Use. Shipping it in the app likely counts as Distribution, which needs the Gemma notice and use restrictions in the app (data plan).

## Decision (team, 2026-11-06)

- **qwen3:0.6b is the primary model, and it runs on-device.**
- **qwen3:0.6b is the fine-tuning target.** Fine-tuning happens after UAT (see "UAT configuration" below).
- **The Gate 2 control is untuned qwen3:0.6b**, evaluated with the same prompts and settings as the tuned model. This supersedes the untuned gemma3:1b control in 0002.
- **gemma3:1b is no longer a fallback.** The draft of this record proposed it as the untuned fallback. This was dropped as a consequence of the team's choice: a larger, slower model (about 40–43 s against 24–26 s for the e2e-009 answer call on the Redmi 10C) can't serve as an on-device fallback. The no-model fallback below replaces it. gemma3:1b stays only as a historical comparison.

## Gate 1 status (2026-11-06)

- **Gate 1 is still FAIL on the test case.** e2e-009 takes about 20 s for a whole question on the Redmi 10C (20.2 s with session files, [0005](0005-gate-1-cold-definition.md)), against the 15 s bar.
- **The planned fix is fine-tuning on the compact results format** (answer prompt v2's format), which shortens the case part.
- Not shown to be enough: e2e-009's compact case part measured 215 tokens on 2026-10-31. That is still over the ~200-token budget below. Whether the tuned model on the compact format passes is unverified.

## Fallback if Gate 1 is not met

- **Status: OPEN, for the team to confirm.**
- **On-device stays.** No server-side model is used. [0001](0001-model-choice.md)'s second fallback (qwen3:1.7b server-side) is not part of this plan.
- **Budget rule:** if a question's answer prompt would exceed the budget, the app does not call the model. It shows the no-model fallback instead: the matching titles and their posted dates (`fallback()` in `e2escore.py`, ported in guard-ts).
  - The budget: the answer call's case part (the answer prompt minus its system turn) is over about 200 tokens, counted with Qwen's tokenizer.
  - The ~200 figure is the 2026-10-31 estimate for the Redmi 10C (devlog). The session-file run agreed with it: the estimate predicted about 19.4 s for e2e-009, and 20.2 s was measured.
- **Cutoff date:** ____
- **Resolved 2026-11-06 (user): a fallback reply does NOT count as passing Gate 1.**
  - e2e-009, the Gate 1 test case, **stays FAIL**.
  - In UAT, long-result questions get the no-model fallback instantly. e2e-009 is one of them (394-token case part).

### UAT configuration (2026-11-06)

UAT is in the week after this record; fine-tuning continues after UAT. UAT ships:

- **untuned qwen3:0.6b**, on-device
- answer prompt v1 (`prompts/e2e_answer_v1.txt`) and query prompt v1 (`prompts/e2e_query_v1.txt`)
- the `and_v2` matcher (search contract v2) in Spring. **Amended 2026-11-07: `and_v3` (search contract v3, and_v2 plus a whole-word plural alternative).** It was adopted under the "nothing gets worse" rule: identical on the dev sets (replay and cold runs, both models), and 8/10 → 9/10 on the labelled flow-test questions. Spring implements v3 directly (`docs/how-it-works.md`).
- session-file caches, one per system turn ([0005](0005-gate-1-cold-definition.md))
- the guard (guard-ts) on the device
- the budget fallback: if the answer prompt's case part is over 200 Qwen tokens, the no-model fallback is shown instead of calling the model. **Amended later the same day; see "Adaptive time budget" below.**

Dev-set effect, from the qwen3:0.6b v1 `and_v1` baseline: 4 of 20 answer calls have case parts over 200 tokens (e2e-002 304, e2e-009 394, e2e-021 408, e2e-032 274). These would get the no-model fallback. The set under `and_v2` is unverified.

#### Adaptive time budget (user decision, 2026-11-06)

- **Why:** on the real snapshot (devlog 2026-11-06), every 2- or 3-result case part is over 200 tokens, so the fixed rule sends every multi-result question to the fallback, on every phone.
- **The rule:**
  - Before the answer call, the app predicts the whole question's time:
    - the time already spent (query call and search, measured)
    - plus the answer session load (200 ms)
    - plus the case part's tokens at this phone's prompt speed
    - plus `GEN_TOKENS` (51) at this phone's generation speed
    - plus 300 ms for the guard and rendering
  - **It falls back only if the prediction is over 15 s.**
  - Where the speed comes from:
    - priming (the last priming call; it generates 16 tokens to measure the generation rate)
    - then each answer call's llama.rn timings
  - `GEN_TOKENS` is the p90 of answer replies with the UAT prompts (29 dev answer calls on Ollama, min 10, median 26, max 53). The phone replies were 37 and 41 tokens.
- **Speed unknown:** for example after an app restart with existing session files, or when timings are missing. The app then uses the **200-token rule** above until an answer call reports timings, so a missing measurement can only make it more conservative. The speed is never saved to disk.
- **n_ctx guard:** a case part over 1548 tokens (2048 − 200 for the answer `n_predict` − 300 for the system turn) always falls back.
- **Logging:** for every question, the app keeps the predicted time, the actual time, the rule used and the result count, never the question or the text. That way UAT can report how often 15 s held.
- **Gate 1 is unchanged.** It is still measured on the Redmi 10C, with the 15 s bar and e2e-009 as the test case. **e2e-009 is still FAIL**, and a fallback reply still does not pass. The adaptive budget is a **UAT product setting, not a new bar**.
- **Replay of the 2026-10-31 Redmi runs** (28 prompt tokens/s, 10.4 generated tokens/s): e2e-009 is predicted at 21.7 s (measured 20.2 s) and falls back; e2e-004 is predicted at 13.9 s (measured 11.9 s) and answers. Both predictions err on the slow side.
- **Unverified:**
  - The first priming call after model load measured about 9 prompt tokens/s against about 28 for the second (2026-10-31). The likely cause is the model being read in after load; this is not confirmed. The rule takes the last priming call's rate, so the slow first call does not set the speed when both run.
  - `ignore_eos` for the measuring priming call has not been tried on the phone.
  - The prediction error on other phones.
- **Amended 2026-11-07:** "until an answer call reports timings" under "Speed unknown" now means until answer calls have reported at least 10 generated tokens in total. See "Results list and short replies" below.

#### Each call kind predicted from its own speed (user decision, 2026-11-07)

- **Where it came from: a test run.** In the Redmi 10C flow test of 2026-11-07, with Prime pressed:
  - Answer priming measured 27.1 prompt tokens/s. Query priming measured 23.8 prompt tokens/s and 14.2 generated tokens/s (the measuring call).
  - `speedFromPriming()` folded the reports in order, so the last call (query) set the prompt rate used to predict **answer** calls.
  - q03 (203 tokens, 2 980 ms elapsed), q07 (200, 2 675) and q09 (199, 3 141) were predicted at 15.6, 15.2 and 15.6 s and fell back.
- **The change:**
  - The answer call is predicted with the answer call's own prompt rate: answer priming, then answer calls.
  - The query call's speed is kept separately (query priming, then query calls). The budget never reads it, because the query call is already measured by the time the budget is decided.
  - The generation rate comes from answer priming if that call measured one, otherwise from the measuring query priming call; then answer calls update it.
  - **`GEN_TOKENS` stays 51 (p90). The 15 s bar, the formula and every constant are unchanged.**
- **Replay with the answer prompt rate (27.1) and the generation rate 14.2:**

  | Question | Case tokens | Elapsed | Old prediction (23.8) | New prediction | New path |
  |---|---|---|---|---|---|
  | q03 | 203 | 2 980 ms | 15 601 ms | 14 562 ms | answer |
  | q07 | 200 | 2 675 ms | 15 170 ms | 14 147 ms | answer |
  | q09 | 199 | 3 141 ms | 15 594 ms | 14 576 ms | answer |
  | q02 | 254 | 2 667 ms | 17 431 ms | 16 131 ms | budget fallback |

- **Why it is principled, not tuned:**
  - The prediction is for the answer call, so it should use a rate measured on the answer call. Before, it used whichever priming call happened to run last.
  - The change moves no threshold and fits no constant to the run. It only stops one call's measurement from standing in for another's.
  - It would have been the right rule before the run. The run is what showed the old fold mixed the two.
  - **Honesty note:** written after seeing the run, which turns these three fallbacks into answers. Gate 1 is unchanged and still FAIL (e2e-009).
- **Caveats:**
  - The generation rate usually still comes from the **query** priming call, the only measuring call. Answer replies generated at 10.4–12.8 tokens/s on the Redmi, against 14.2 here, so the generation part of the prediction may be optimistic until answer calls update it. A reply of 51 tokens at 12.7 instead of 14.2 adds about 0.4 s.
  - **Open:** making answer priming the measuring call instead.
  - If the first priming call after model load is slow (about 9 tokens/s on 2026-10-31), the answer prompt rate is now pessimistic until answer calls update it. That falls back more, never less.

#### Results list and short replies (user decision, 2026-11-07)

- **Evidence: the Redmi 10C flow test of 2026-11-07** (devlog). The real assistant-ts and guard-ts ran on the phone's Hermes, with the parity vectors passing, on 10 test questions against the real snapshot.
  - All 3 answer calls replied with the not-found sentence although a result was retrieved (q06, q07, q09).
  - On Ollama, cold, with the same results, the same sentence came back 3 of 3.
  - In each case the needed fact was inside the excerpt the model saw, with no HTML tags or entities left. So the untuned model misses facts that are present.
- **Results list on every path with results:**
  - The text ends with `These announcements may help:` and one line per result (title and posted date).
  - On the `answer` path, the guarded reply goes above the list.
  - On `guard_fired`, `budget_fallback` and `answer_error`, the list is the whole text. This replaces the old `I found these announcements:` fallback text.
  - The guard and its fallback function are unchanged.
- **New path `answer_not_found`:** the reply is exactly the not-found sentence after the ASCII trim, although results exist. The list is shown instead of "not found".
  - An exact match, because the prompt asks for only that sentence and all 6 observed replies (3 on the phone, 3 on Ollama) were exact.
  - `not_found` (no results) is unchanged.
- **Short answer replies add up for the speed:**
  - A generated rate needs at least 10 tokens. The 8-token not-found sentence never qualified, and the tokens rule sent most other questions to the fallback before any answer call, so the speed could stay unknown until the next priming.
  - Now answer replies under 10 tokens add their tokens and ms to a running total, and at 10 tokens the total becomes the rate. Answer calls only; priming is unchanged.
  - The phone's 8-token replies generated at 12.7–12.8 tokens/s, in line with longer answers (10.4–12.8).
- **Gate 1 is unchanged.** These are UAT product settings: the list is built from data, not by the model. Dev eval scoring still scores the model's reply.

## Caveats

- **Dev set only:** 34 cases we wrote ourselves. The held-out set has not been run.
- **One run each:** qwen3:0.6b's baseline is one cold run; gemma3:1b's is two identical cold runs. Cold greedy runs have repeated exactly so far, but that is not proof for the held-out set.
- **The regression set (e2e-025 to 034) was written after seeing retrieval failures**, so its hit rates are not evidence of general retrieval quality.
- **Gate 1 is still FAIL for both models.** This record does not claim either one passes.
- Phone numbers come from one development build on one Redmi 10C; release-build behaviour is unverified.
- The differences on the dev set are small (`and_v1`: 8 vs 10 failures, 27 vs 28 retrieval hits; `and_v2`: 6 vs 5 failures, 30 vs 33 retrieval hits, qwen3:0.6b first) and may not hold on the held-out set.

## Consequences

- **The fine-tuning target becomes qwen3:0.6b.** `docs/plans/finetune-data-plan.md` is written for gemma3:1b and needs rework:
  - the training render must follow qwen3:0.6b's template, including the empty `<think>` block that `"think": false` produces (`render.py` has only `render_gemma3()`)
  - the `<bos>` rule (Decision 3) does not apply as written, because Ollama adds no start-of-text token for qwen3:0.6b
  - the export path's Q4_K_M check, template copy and stop strings (`<|im_end|>`, `<|im_start|>`) change
- **qwen3:0.6b's retrieval misses become the main quality risk.** 7/34 cases miss because of the query it writes in the query call. Five of them fail; the other two (e2e-003, 021) are not-found traps whose replies still passed. Meanwhile the data plan trains the answer call only (Decision 1). Options include training the query call too, or changing the matcher (`fts_v3` is deferred). Under `and_v2` (now the default), 4/34 cases miss (e2e-003, 014, 021, 023). Two of them fail (e2e-014, 023); e2e-003 and 021 are not-found traps whose replies still passed.
- 0002's Gate 2 metrics and protocol are unchanged; only the model and its control change.
- Gate 1 must still be passed on the Redmi 10C with the chosen model.

## Unverified

- Why qwen3:0.6b's phone PSS is about twice gemma3:1b's.
- Whether qwen3:0.6b's reply stability holds on other phones.
- Whether the dev-set differences hold on the held-out set.
