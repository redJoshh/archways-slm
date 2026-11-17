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
- **Human review (2026-11-14):** the user reviews the private report of both held-out runs. Each run reports Unsafe as scored and as human-reviewed, side by side. scorer_v1 can't detect a reply that contradicts its source on a yes/no question, or one that mixes up which listed announcement says what.
- **Drift check (2026-11-14):** before the final run, `eval_flow.py --verify-baseline data/local/runs/baseline-1.json` must print `VERIFY OK` at the same commit, with a clean tree. It proves the baseline configuration still reproduces the frozen dev baseline case by case.
- **Two runs, then closed (user, 2026-11-16):** this held-out set is used at most twice, `--config baseline` (done 2026-11-14) and `--config final`. After the final run it is closed: any further improvement is a v2, evaluated on a NEW held-out set written for it. The same rules apply to the new set (written before the v2 changes are measured, never read by Claude Code, at most two runs).
- **What the held-out runs measured vs. what ships (user, 2026-11-17):** both held-out runs are closed (baseline 2026-11-14 at `53f2ed3`, final 2026-11-17 at `428b1ca`, `--config final`). The shipped app = the evaluated FINAL configuration + window_v1 (ADR 0006 amendment), a phone-only setting outside `frozen.FINAL`. window_v1 provably can't change any dev or held-out result at the evaluation dates: no visible snapshot row is older than 30 days at 2026-11-10 or 2026-11-14 (`tests/test_window_fallback.py`). It does change behaviour from about 2026-12-07 on (its purpose), so the held-out numbers don't describe the app after that date. Any measurement of it is a v2 on a new held-out set.
- **v2 held-out protocol (user, 2026-11-17):** the v1 set stays closed. The v2 phase ([`v2-improvements.md`](../plans/v2-improvements.md)) uses a NEW file written by the user.
  - **The file:** 30 cases (24 answerable, 6 traps), snapshot only, never read by Claude Code.
  - **Hash:** its SHA-256 `EE9F407AF9BD8899C1D247DCEE10330DD1D2860B13E3C6F6482C81FD5839173C` was recorded before any v2 fix, and the script refuses any other file for a v2 config.
  - **Fixed now:** 2026-11-17T10:00:00+08:00.
  - **Baseline:** `--config shipped` (FINAL + window_v1, what the app ships). **Final:** the v2 kept set.
  - **Runs:** at most two, by the user, with the same manual review and scored and human-reviewed numbers side by side.
  - **Drift check:** `VERIFY OK` at the run commit, clean tree, before the baseline.
  - **Rules for v2 changes:** the same no-training rule. Each change is pre-registered, with parity and dev-only scoring, plus "no case loses AI-correct". The kept set is frozen by 2026-12-01.
- **No pass/fail thresholds** are set in this ADR. The held-out run reports the baseline and final counts side by side. With so few cases it is a check that the dev-set gains carry over, not an error rate.

## Consequences

- Prompt design is in scope, so failures once filed as fine-tuning targets are candidates for prompt-level fixes. Example: the past-date framing ("is held" for a past event, flow q12) is a candidate prompt fix for a later phase. In this phase q12 scores only the date (user, 2026-11-14).
- Every gain must come from rules that are written and frozen before they are measured, with Python/TS parity vectors.
- `tests/test_e2e_harness.py::test_no_code_reads_the_held_out_file` stays: the held-out path is given only on the command line.

## Open

- Acceptance by the user.
