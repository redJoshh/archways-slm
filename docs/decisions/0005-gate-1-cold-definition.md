# 0005: What "cold" means for Gate 1

- **Status:** ACCEPTED (user decision, 2026-10-31; team agreement unverified)
- **Date:** 2026-10-31
- **Amends:** the definition of "cold" in [0003](0003-gate-1-pass-bar.md). 0003's bar (a whole question in under 15 s on the Redmi 10C, first model load under 10 s) and its test case (e2e-009) are unchanged.

## Context

- 0003 defines a cold answer as "the first run after loading the model, with no prompt-cache reuse".
- llama.rn 0.13.0-rc.8 can save the model's state after a prompt to a session file and load it again (`saveSession`/`loadSession`). The app can save each call's system turn once and load it before every question, so only the question-specific part is processed.
- Read literally, 0003's "no prompt-cache reuse" also forbids this, although production would do it on every question.
- Session-file test on the Redmi 10C, qwen3:0.6b, answer prompt v1, 2026-10-31 (devlog of that date):
  - Priming, once: the answer system turn (197 tokens) in 22.0 s and the query system turn (213 tokens) in 7.7 s.
  - After a fresh model load, each question was: load the query session file, run the query call, load the answer session file, run the answer call.
    - e2e-004: whole question 11.9 s, and 12.4 s on a repeat.
    - e2e-009: 20.2 s.
  - Session loads took 0.1–0.2 s.

## Honesty note

This record was written on 2026-10-31, **after** the session-file results above were seen.

It does not move the bar:

- The 15 s limit, the reference device and the test case (e2e-009) are unchanged.
- It allows only what production does on every question: loading system turns saved once, before any question is asked. Reuse of anything from an earlier question stays excluded.
- Under this definition **Gate 1 is still FAIL**: e2e-009 takes 20.2 s.

## Decision

- **Cold excludes** any reuse of an earlier question's prompt. That covers the in-memory prompt cache left by a previous question, and any state saved after a question's own text.
- **Cold includes** loading the saved system-turn session files, one per call (query and answer).
  - Each timed question starts from a fresh model load, or from a state that holds no earlier question.
  - Its wall time counts the session loads, the query call, the search and the answer call, from send to final reply (0003).
- **Priming** (processing and saving the system turns, about 30 s on the Redmi 10C with qwen3:0.6b and answer prompt v1) is **reported separately, like model load**. This record sets no bar for it.
- **e2e-009 remains the test case.**

## Consequences

- The 2026-10-31 session-file runs count as cold under this definition, except that they leave out the Spring search call. So they are lower bounds on the whole question.
- The answer prompt v1 has today's date in its system turn, so a saved answer session file is valid for one day only, and priming happens again each day. Answer prompt v3 (date in the user turn) would make the file valid across days if it is adopted.

## Unverified

- The Spring search call's time on the phone's network.
- Whether session files stay valid across app restarts and model reloads, and how large they are on disk.
- Release-build behaviour; all phone runs so far use a development build.
