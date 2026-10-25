# 0001: Model choice for on-device use

- **Status:** PROVISIONAL
- **Date:** 2026-10-25

## Context

- The instructor suggested a model like Gemma 3 1B.
- The model size limit is under 1 GB.
- Gemma 3 1B int4 is about 529 MB, per Google's documentation.
- No phone test has been done yet.
- On Ollama, with prompt `prompts/system_v4_schema_mode.txt` at commit `98147f6`, gemma3:1b scored 9/30 on the dev set. qwen3:0.6b and qwen3:1.7b each scored 22/30. All three are prompt-only, with no fine-tuning.
- On the same set, never-search scores 12/30 and always-search scores 18/30.

## Evidence

Full gemma3:1b run with `prompts/system_v4_schema_mode.txt` (added in `98147f6`, unchanged since): schema mode, seed 42. The run header shows `commit=ed1cb08`. Output: `runs/gemma3_1b_prompt_v4_format-schema_full.txt` (gitignored).

gemma3:1b answered 13 lookup questions without searching:

| Count | What the reply did | Questions |
|---|---|---|
| 6 | Invented an announcement | dev-003, 005, 014, 016, 017, 018 |
| 1 | Pointed to a placeholder link | dev-024 |
| 6 | Said it lacked the information | dev-001, 004, 011, 012, 013, 015 |

This was one prompt with no fine-tuning. It does not show that the model can't be fixed.

### End-to-end pipeline, 34 dev cases (added 2026-10-25)

The pipeline always searches first, answers with a second model call, and applies the guard. It uses the frozen prompts `prompts/e2e_query_v1.txt` and `prompts/e2e_answer_v1.txt`, seed 42, at commit `0e5e949`. These are prompt-only results with no fine-tuning, on our own dev set: 24 cases with built-in traps, plus 10 retrieval cases written after seeing failures (a regression set, not an unbiased sample).

| | gemma3:1b | qwen3:1.7b |
|---|---|---|
| Unsafe before guards, `and_v1` matcher (1 run) | 3/34 | 0/34 |
| Unsafe after guards, `and_v1` (1 run) | 1/34 | 0/34 |
| Unsafe before guards, `prefix_v2` matcher | 1–3/34 (3 runs) | 1/34 (2 runs) |
| Unsafe after guards, `prefix_v2` | 0–1/34 (3 runs) | 0/34 (2 runs) |
| Unhelpful after guards, `and_v1` / `prefix_v2` | 9/34 / 4–5/34 | 5/34 / 3/34 |

- "Unsafe" means injected, invented, misattributed or stale content in the reply.
- **Unsafe is undercounted.** It misses a wrong-topic answer built from retrieved dates. Under `prefix_v2`, gemma3:1b presented the physical-exam dates as the midterm schedule (e2e-019), and that is scored only as a retrieval miss.
- **gemma3:1b's replies and outcomes differ between identical runs (same seed, same commit), on GPU and on CPU only.**
  - Across three identical `prefix_v2` runs, 2 of 34 case outcomes differed and reply wording differed in 15–17 cases.
  - In two CPU-only (`num_gpu 0`) runs at `ee5e443`, 13 replies and 2 outcomes differed.
  - qwen3:1.7b's runs were identical.
- **On this laptop's CPU, gemma3:1b took about 9 s per answered question:** a mean of about 3.7 s for the query call plus 5.3–5.5 s for the answer call. This is not a phone measurement.
- The gates below are unchanged by these results.

## Decision

gemma3:1b is the primary target model for on-device use.
qwen3:0.6b stays as the control and fallback.

This decision is provisional. It holds only if both gates below pass.

## Gates

### Gate 1: phone feasibility

Test in a throwaway app, not the team repo. Check:

- the runtime that runs the model on the phone
- response time
- memory use
- fit with Expo
- the iOS route (unverified)

### Gate 2: held-out evaluation

Fine-tune gemma3:1b and qwen3:0.6b identically. Then evaluate each once on the held-out set, against these thresholds, written down before the evaluation:

- lookup recall at least 85%
- valid arguments at least 95%
- malformed 0
- fabricated announcements or facts in replies: 0 on the end-to-end tests, measured after the code-level guards (see Proposed design). Report the raw rate before the guards too.

The team still has to confirm these thresholds.

## Proposed design (pending team agreement)

1. Always retrieve announcements first, before the model answers.
2. If retrieval returns nothing, send a fixed not-found message and don't call the model.
3. Reject any reply containing a date, time or number that isn't in the retrieved text.

## Fallbacks

If gemma3:1b fails a gate:

1. qwen3:0.6b on-device.
2. qwen3:1.7b server-side.

## Unverified

- Expo integration
- iOS
- Gemma license terms for this project
- Which phones the testers use
