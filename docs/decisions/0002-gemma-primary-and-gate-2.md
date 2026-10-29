# 0002: gemma3:1b as the primary model, fine-tuning, and Gate 2 on end-to-end metrics

- **Status:** ACCEPTED (team decision)
- **Date:** 2026-10-29
- **Supersedes:** the Decision section and Gate 2 of [0001](0001-model-choice.md). Gate 1 and the rest of 0001 still apply.

## Context

- [0001](0001-model-choice.md) made gemma3:1b the provisional primary model, with two gates. Its Gate 2 used tool-decision thresholds (lookup recall, valid arguments).
- The pipeline now always retrieves first: the model writes only the search arguments, code runs the search, and a second call answers from the results (see `scripts/probe_end_to_end.py`). The model no longer decides whether to search, so lookup recall and valid tool arguments no longer measure it.
- With greedy options, one `ollama serve` with `OLLAMA_NUM_PARALLEL=1`, `--num-gpu 0` and `--keep-alive 0`, gemma3:1b's replies repeated exactly. With the model kept loaded, they depended on the previous call. Evidence: the devlog entries of 2026-10-29.

## Decision

- **gemma3:1b is the primary model** (team decision).
- **Fine-tuning is confirmed, for gemma3:1b only.**
- **The Gate 2 control is untuned gemma3:1b**, evaluated with the same prompts and settings as the fine-tuned model.
- **qwen3:0.6b stays as an untuned fallback.** It is no longer fine-tuned alongside gemma3:1b.
- 0001's second fallback (qwen3:1.7b server-side) is not changed by this record.

## Gates

### Gate 1: phone feasibility

Unchanged from 0001, and still not done.

### Gate 2: held-out end-to-end evaluation

Gate 2 uses the end-to-end metrics from `scripts/probe_end_to_end.py`, measured on the held-out set. They replace 0001's thresholds. Lookup recall and valid arguments no longer apply under always-retrieve-first.

Thresholds, written down before any held-out run:

- **Unsafe after guards:** 0.
- **Unhelpful after guards:** at most 20% of in-scope held-out cases, rounded down to a whole number of cases.
  - Held-out cases that are out of v1 scope by design are scored on safety only: they pass if the reply is the not-found message or a safe decline, and fail only if unsafe.
  - Which cases are out of scope is decided by the user, by hand, and written down before the held-out run. Claude Code never reads the held-out file to decide this.
  - With so few held-out cases, this gate is a smoke test, not an error rate.
  - The probe does not yet score out-of-scope cases on safety only, or recognize a safe decline; that is still to build.
- **No worse than the control:** the fine-tuned model must be no worse than the untuned control on unsafe after guards and on unhelpful after guards.
- **Malformed outputs:** 0, measured as the probe's `invalid search arguments` count (a query reply that is not a JSON object, or that the contract rejects). Answer replies are free text, so they cannot be malformed.

Reported but not gated:

- unsafe before guards
- retrieval hit rate

### Measurement protocol

- One `ollama serve` started with `OLLAMA_NUM_PARALLEL=1`.
- `--num-gpu 0` and `--keep-alive 0`.
- The greedy options `temperature 0`, `top_k 1`, `top_p 1`, `seed 42` (`SAMPLING_OPTIONS`, printed in every run header).
- The Ollama version is recorded from the run header and does not change during Gate 2.
- **Gate 2 is decided on the cold run** (the settings above).
- One warm run (default keep-alive, no `--keep-alive`) is reported alongside. It is not gated.

## Rules

- **No dev, e2e or held-out question, or a paraphrase of one, may appear in training data.**
- The existing leak tests must be extended to the training data before any training run. Today, `tests/test_prompts.py` checks only the prompt files against the dev and e2e questions (exact text, and word overlap for prompt examples). `tests/test_e2e_harness.py` checks that no code reads the held-out file. Nothing checks training data yet, because there is none in the repo.
- How training data will be checked against the held-out questions, which must not be read by code, is unverified.

## Open

- **Warm versus cold:** the phone runs the model warm, so production replies can differ from the cold evaluation. The warm run shows how much, but it is not gated.
- **The held-out run is blocked** until real published announcements are available.
- Gate 1 is not started.

## Unverified

- Whether the cold-run determinism seen on the 34 dev cases also holds on the held-out set.
