# 0004: qwen3:0.6b as the primary model

- **Status:** PROPOSED. Not accepted; the team decides.
- **Date:** 2026-10-31
- **Would supersede, if accepted:** in [0002](0002-gemma-primary-and-gate-2.md), "gemma3:1b is the primary model", "fine-tuning is confirmed, for gemma3:1b only", the untuned gemma3:1b Gate 2 control, and qwen3:0.6b as the untuned fallback. Gate 2's metrics and protocol in 0002, and Gate 1 in [0001](0001-model-choice.md) with its pass bar in [0003](0003-gate-1-pass-bar.md), would still apply.

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

## Proposal

- **qwen3:0.6b becomes the primary on-device model** and the fine-tuning target.
- **The Gate 2 control becomes untuned qwen3:0.6b**, evaluated with the same prompts and settings as the tuned model.
- **gemma3:1b becomes the untuned fallback.**

## Caveats

- **Dev set only:** 34 cases we wrote ourselves. The held-out set has not been run.
- **One run each:** qwen3:0.6b's baseline is one cold run; gemma3:1b's is two identical cold runs. Cold greedy runs have repeated exactly so far, but that is not proof for the held-out set.
- **The regression set (e2e-025 to 034) was written after seeing retrieval failures**, so its hit rates are not evidence of general retrieval quality.
- **Gate 1 is still FAIL for both models.** This record does not claim either one passes.
- Phone numbers come from one development build on one Redmi 10C; release-build behaviour is unverified.
- The differences on the dev set are small (8 vs 10 failures, 27 vs 28 retrieval hits) and may not hold on the held-out set.

## Consequences if accepted

- **The fine-tuning target becomes qwen3:0.6b.** `docs/plans/finetune-data-plan.md` is written for gemma3:1b and needs rework:
  - the training render must follow qwen3:0.6b's template, including the empty `<think>` block that `"think": false` produces (`render.py` has only `render_gemma3()`)
  - the `<bos>` rule (Decision 3) does not apply as written, because Ollama adds no start-of-text token for qwen3:0.6b
  - the export path's Q4_K_M check, template copy and stop strings (`<|im_end|>`, `<|im_start|>`) change
- **qwen3:0.6b's retrieval misses become the main quality risk.** 7/34 cases miss because of the query it writes in the query call. Five of them fail; the other two (e2e-003, 021) are not-found traps whose replies still passed. Meanwhile the data plan trains the answer call only (Decision 1). Options include training the query call too, or changing the matcher (`fts_v3` is deferred).
- 0002's Gate 2 metrics and protocol are unchanged; only the model and its control change.
- Gate 1 must still be passed on the Redmi 10C with the chosen model.

## Unverified

- Why qwen3:0.6b's phone PSS is about twice gemma3:1b's.
- Whether qwen3:0.6b's reply stability holds on other phones.
- Whether the dev-set differences hold on the held-out set.
