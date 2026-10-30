# 0003: Gate 1 pass bar

- **Status:** ACCEPTED (user decision, 2026-10-30; team agreement unverified)
- **Date:** 2026-10-30
- **Amends:** Gate 1 of [0001](0001-model-choice.md), which listed what to check but set no pass bar. The rest of 0001 and [0002](0002-gemma-primary-and-gate-2.md) still apply.

## Context

- 0001's Gate 1 (phone feasibility) lists checks (runtime, response time, memory use, fit with Expo, the iOS route) but no threshold. 0002 left Gate 1 unchanged.
- First phone measurements, 2026-10-30, gemma3:1b on llama.rn 0.13.0-rc.8, CPU only, with the answer call of e2e-009 (`runs/gate1_prompt.txt`, 631 tokens, the longest answer prompt in the e2e cases). Evidence: the devlog entries of 2026-10-30.
  - Nothing Phone 3a Pro: one cold answer in 16.9 s.
  - Redmi 10C, 4 GB RAM: four cold answers in 39.5–43.2 s, of which 34.1–36.8 s is prompt processing.

## Honesty note

This bar was set on 2026-10-30, **after** gemma3:1b's cold answers on the Redmi 10C were measured at about 40–43 s, but **before** any optimization and before any qwen3:0.6b phone test.

It must not be changed after seeing further results. A change needs a new decision record that gives the reasons.

## Decision

### Reference device

- **Redmi 10C, 4 GB RAM**, the weakest target phone.
- Results on stronger phones are reported but never decide Gate 1.

### Speed

- **A cold answer takes under 15 s total wall time on the reference device.**
- Cold means the first run after loading the model, with no prompt-cache reuse.
- Measured on the production-shaped answer prompt for the test case, not a shortened toy prompt. The test case is e2e-009's answer call (`runs/gate1_prompt.txt` for gemma3:1b).

### Stability

- **No crash or restart** when the app is sent to the background for about a minute and reopened, and **it still answers**.

### Levers

Every lever (prompt length, system-prompt caching, a smaller model, fine-tuning) is measured against this same bar.

## Current status (2026-10-30)

- **Speed: FAIL.** gemma3:1b with the current 631-token prompt takes about 40–43 s cold on the Redmi 10C (39.5–43.2 s measured across four cold runs).
- **Stability:** with `use_mmap: true`, the app survived Android swapping it out and answered after returning. The process was not killed. How long it was in the background was not recorded.
- Gate 1 is not passed.

## Open

- **Total wall time** has so far been the runtime's reported prompt plus generation time; model load (2.0 s on the Nothing, 4.9 s first load on the Redmi) was reported separately. Whether the bar includes model load is not written down yet.
- **The bar covers the answer call only.** The app also makes a query call before it (245 prompt tokens for e2e-009 on Ollama), which is not timed on the phone yet.
- 0001's other Gate 1 checks (memory use, fit with Expo, the iOS route) have no threshold here. They are still reported.

## Unverified

- Memory and speed in a release build; all phone runs so far use a development build.
- Whether the Redmi 10C results hold with other apps open.
