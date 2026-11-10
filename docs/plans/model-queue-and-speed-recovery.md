# Plan: one serial model queue, exclusive priming, and answer-speed recovery

**Status:** approved by the user to build (2026-11-10, "fix, plan first"). This plan is committed before any code. The constants below are fixed here and not tuned afterwards.
Source: the Redmi 10C live run of 2026-11-10 (devlog).

## The two bugs

1. **Concurrency.**
   - What happened: a question was asked while Prime was running and the index was building. llama.rn rejected the query call after 118 ms, with no timings, so the question ended in `query_error` and the last-resort text.
   - Why: nothing in assistant-ts stops two model calls from running at once.
2. **Speed lock-in.**
   - **The bad sample:** the measuring priming call ran while the index fetch and the failed call overlapped it, and measured 6.7 generated tokens/s. Because the query kind is primed last and measures, the answer speed borrows that rate. The session's query calls later ran at 13.6–15.0.
   - **The effect:** the Misa question (212 case tokens) was predicted at 17,440 ms, so `budget_fallback`.
   - **Why it never corrects:** the answer speed updates only from answer calls, and on the Redmi almost every question falls back before one is made.

## Design

### A. `queue.ts`: `createModelQueue()` (TS only; async orchestration has no Python counterpart)

- **`run(job)`:** every model call goes through it, first in, first out, one at a time. It resolves to `{ value, overlap }`.
- **`exclusive(job)`:** used for priming and re-measuring.
  - It runs after the jobs already queued, and only once no **activity** is active.
  - While an exclusive job is queued or running, `beginActivity()` waits, so no new activity can start.
- **`beginActivity()`:** the app's non-model work that competes for the CPU. In this plan that is the feed index build and refresh (`createFeedIndex` gets an `activity` option).
  - It resolves to an `end()` function once no exclusive job is queued or running.
  - Exclusive jobs wait only for activities that already started, so there is no deadlock.
- **`overlap`:** true if any activity was active at any moment during the job (active when it began, or begun during it).
  - Activities are the only overlap source left: model jobs can't overlap each other by construction.
- **`busy()` / `whenIdle()`:** whether an exclusive job is queued or running, and a promise for when none is.
- **`onChange(listener)`:** for the app's "getting ready" state.

### B. Sessions and the runtime

- `makeComplete(llama, settings, queue?)`: with a queue, the session load and the completion run as one `queue.run` job, and the returned `Completion` carries `overlap`.
- `primeSessions(..., queue?)`: with a queue, each `primeOne` is one `queue.exclusive` job, and `PrimeReport.overlap` is set.
- **New `runtime.ts`, `createAssistantRuntime({ llama, settings, clockMs? })`:** the one object an app needs.
  - **`prime(nowMs)`:**
    - Primes the sessions through the queue. The state goes `"priming"` → `"ready"`.
    - Seeds `speed` and `querySpeed` from `speedsFromPriming(reports)`. Reports flagged `overlap` are skipped (C).
    - Afterwards it calls `remeasureIfNeeded`.
  - **`state()`** returns `"not_primed" | "priming" | "measuring" | "ready"`. `onChange(listener)` reports changes.
  - **`whenReady()`** resolves when no priming or re-measure is queued or running.
  - **`beginActivity()`** passes through to the queue.
  - **`deps()`** returns `{ complete, countTokens, speed, querySpeed, whenReady }`. The app adds `nowMs`, `search` and `log`.
  - **`ask(question, extra)`:** `askAssistant` with `deps()`, then `remeasureIfNeeded` (D).

### C. Samples taken under overlap are invalid (Python reference + TS + vectors)

- `speeds_from_priming` / `speedsFromPriming` skip any report whose `overlap` is true. The rest of the rule is unchanged, including the answer speed borrowing the query speed's generation rate.
  - Python reports become `(kind, timings)` or `(kind, timings, overlap)`.
- In `askAssistant`, a `Completion` with `overlap: true` updates neither `speed` nor `querySpeed`.
- **Vectors:** priming cases where the measuring report, an answer report, or both are flagged `overlap`.

### D. Recovery rule: re-measure when the answer generation rate is suspect

- **Suspect** (pure; Python `answer_speed_suspect(answer, query)`, TS `answerSpeedSuspect()`, with vectors) is true if either holds:
  - the answer speed has no generation rate, or
  - both generation rates are known and `answer.genTps < SUSPECT_RATIO × query.genTps`.
- **`SUSPECT_RATIO = 0.6`.** It comes only from the honest samples of 2026-11-07, not from the Misa question.
  - On the Redmi, answer calls generated at 10.4–12.8 tokens/s against query calls at 14.2–14.6: ratios of 0.71–0.90.
  - 0.6 sits below the lowest of them, with a margin.
  - The constant goes through the generator.
- **The action (runtime):** after priming and after each question, if suspect, queue one exclusive re-measure.
  - The re-measure is `primeOne(answer, measure = true)`. It processes the full answer prefix, so it gives both rates, and generates `MEASURE_TOKENS` tokens. It re-saves the same session.
  - Its timings go through `speed.update()` only if the job had no overlap.
  - The state is `"measuring"` meanwhile. Questions wait for it like priming (`whenReady`).
- **Limits:**
  - One re-measure queued at a time.
  - At most `REMEASURE_MAX_PER_DAY = 2` per Manila day (the session day). An overlapped re-measure counts too.
  - A valid re-measure is the truth, even if it is still low. The limit stops loops on a phone that really is slow.
- **No bounded correction of the prediction.**
  - A floor such as 0.6 × the query rate would be over-optimistic after a valid re-measure confirms a slow phone. It would also need extra state to switch off.
  - Even with the floor, the Misa question would have been predicted at about 16.1 s, so it would still fall back (worked out below). The rule doesn't aim to flip any one question.
- **Worked example** (for the record, not a target):
  - The recorded prediction was 17,440 ms = elapsed (≈ 2,423) + 200 + 212 × 1000/30.7 + 51 × 1000/6.7 + 300.
  - With the rule:
    - The bad sample would most likely not exist (A, exclusive priming).
    - If it did, the overlap flag (C) drops it.
    - If it were unflagged, Misa's own query call would set the query rate to about 13.6, so the answer rate (6.7) is suspect. A re-measure follows, and the next question uses the measured rate.

### E. `askAssistant` waits for readiness

- **`deps.whenReady?: () => Promise<void>`** is awaited before the question starts. The question's clock, and the budget's elapsed time, start after it.
  - The wait is reported as `readyWaitMs` in `AssistantResult` and `QuestionLog`.
  - The 15 s budget is about the model work. The app shows "getting ready" during the wait.
- **No `whenReady`** (for example the vectors and the old wiring): the behaviour is unchanged.
- **The serial queue still protects** a question that arrives without `whenReady`, or while another question is running: its calls wait their turn instead of failing.

## Tests (written with the code; vectors before the implementation)

- **Python:**
  - `speeds_from_priming` with overlap flags.
  - `answer_speed_suspect`, including the boundary at exactly 0.6 × the query rate (not suspect), just under it, missing rates and an unknown query rate.
  - Vectors exported for TS.
- **Node:**
  - **Queue:** FIFO order; one job at a time; an exclusive job waits for a running activity; `beginActivity` waits for a queued or running exclusive job; overlap is set when an activity begins mid-job.
  - **A question arriving during priming:** no query completion starts until priming resolves. The path is `answer` (not `query_error`), and `readyWaitMs > 0`.
  - **Overlap:** an overlapped answer `Completion` doesn't change the speed.
  - **Re-measure:** a suspect speed queues exactly one re-measure, the day limit holds, and an overlapped re-measure is discarded.
  - A feed index build waits while priming runs.
- **Hermes CLI:** the vectors plus the "question during priming" scenario, run through the real `createAssistantRuntime` with promise-controlled fakes (no timers).
- **Mutation checks:**
  - `run` not serial
  - exclusive not waiting for activities
  - the overlap flag ignored in `speedsFromPriming`
  - `<` changed to `<=` in the suspect rule
  - the day limit off
- **Test app:** `phoneModel.ts` and the screens use `createAssistantRuntime`. The live screen's index build goes through `beginActivity`, and the screens show the runtime state.
- **Phone runs (user):** on the Redmi, ask during Prime and during the index build.

## Not in this plan

- Background loading at app start (the mobile note of 2026-11-10) is the app's job: call `runtime.prime()` once the model is loaded.
- Other CPU users the app doesn't register as activities (for example a heavy screen render) are not detected.
