# 0007: No training; accuracy from tools, safeguards and prompts; the held-out protocol

- **Status:** PROPOSED (drafted 2026-11-14, for the user's approval)
- **Date:** 2026-11-14
- **Supersedes (on acceptance):** [0002](0002-gemma-primary-and-gate-2.md)'s Gate 2 (held-out end-to-end evaluation of a fine-tuned model against the untuned control) and the fine-tuning parts of 0002 and [0004](0004-model-choice-qwen.md) that are still open. The cold measurement protocol in 0002 stays.
- **Plan:** [`docs/plans/accuracy-phase.md`](../plans/accuracy-phase.md), sections 0 and 2 (frozen 2026-11-14).

## Context

- The team committed to the panel that the assistant is **not trained or fine-tuned**. Accuracy may be improved only with tools, code-level safeguards and prompt design.
- The model stays qwen3:0.6b. The search stays on the phone ([0006](0006-on-device-search-over-the-feed.md)). No backend change.
- 0002's Gate 2 compared a fine-tuned model with the untuned control on the held-out set. With no fine-tuning, there is nothing for that gate to decide.
- The held-out file has never been run. A held-out set that is run repeatedly while changes are chosen turns into a dev set.

## Decision

### 1. No training

- No training, fine-tuning, adapters or distillation of any model, in this project's code or outside it.
- Allowed: tools (search, ranking, retry), code-level safeguards (guards, gates, fallbacks), prompt design (new prompt versions in `prompts/`), and data the code reads at query time.
- `docs/plans/finetune-data-plan.md` is kept for the record only. Nothing in it is built.

### 2. Metrics

The three metrics of `accuracy-phase.md` section 0 (Helpfulness, AI answer accuracy, Unsafe), always as counts, per set and in total.

### 3. The held-out protocol (replaces Gate 2)

- **The script:** `scripts/eval_heldout.py PATH`. It runs the full flow and the frozen scorer_v1, with a fixed `now` of 2026-11-14T10:00:00+08:00 for every case.
  - It prints only the file's SHA-256, the case count, the configuration and the totals.
  - It prints no per-case line, id, question or reply, and writes nothing to disk (except the private report, below, when asked for).
- **At most two runs:**
  1. the baseline, after the harness, scorer_v1 and the dev baseline are frozen
  2. the final run, after every change is frozen
- **Never in between,** and never to choose between changes.
- **The user runs it.** Claude Code never runs the script, opens or reads the held-out file, or asks for its contents. The user pastes the totals; the devlog records them with the file's SHA-256, which must match between the two runs.
- **Private report (amendment, 2026-11-14):** `--private-report PATH` writes a per-case report to a path outside the repository, for the user's manual review. Only the user reads it; it never enters the repo, the devlog or a chat. Without the option nothing is written.
- **Frozen at `9bf6e72`:** scorer_v1 and the held-out script.
- **No pass/fail thresholds** are set in this ADR. The held-out run reports the baseline and final counts side by side. With so few cases it is a check that the dev-set gains carry over, not an error rate.

## Consequences

- Prompt design is in scope, so failures once filed as fine-tuning targets are candidates for prompt-level fixes. Example: the past-date framing ("is held" for a past event, flow q12) is a candidate prompt fix for a later phase. In this phase q12 scores only the date (user, 2026-11-14).
- Every gain must come from rules that are written and frozen before they are measured, with Python/TS parity vectors.
- `tests/test_e2e_harness.py::test_no_code_reads_the_held_out_file` stays: the held-out path is given only on the command line.

## Open

- Acceptance by the user.
