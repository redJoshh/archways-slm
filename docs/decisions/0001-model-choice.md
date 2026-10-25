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
