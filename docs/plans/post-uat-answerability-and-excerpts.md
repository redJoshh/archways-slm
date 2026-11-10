# Post-UAT plan: answerability gate and excerpt length

**Status:** both parts **approved as post-UAT** (user, 2026-11-10). Nothing is built yet.
Source: the Nothing Phone 3a Pro flow run and the snapshot checks (devlog, 2026-11-10).

## Rules for both parts

- **No tuning on the 10 flow questions.** They are read out only once the rule and its numbers are frozen.
- **The held-out file is used only for the final comparison.**
- **"Nothing gets worse":** a change is kept only if, on every set (e2e34 and Taglish10 on qwen3:0.6b, replay first and then cold), no count gets worse:
  - answerable `answer` paths
  - retrieval hits
  - traps clean
  - failed after guards
  - unsafe before and after guards
- **Every rule gets:**
  - a Python reference
  - parity vectors exported for assistant-ts
  - Node and Hermes runs
  - a mutation check
  - a phone run before it ships

## (a) Answerability gate

**Goal:** skip the answer call when no result is about the question. The flow q01 case shows why: the reply took an office from an unrelated top result (row 59), and the guard passed it.

**Proposed rule:**

1. **Question words:** take the question's words with the and_v3 tokenizer (`WORD_RANGES`) and the same stopword handling. Anchors are a subset of them: numbers, dates and runs of capitalised words.
2. **Coverage:** for each result, coverage = the share of question words found as whole words in the title plus the **full plain text**. Since ADR 0006 the full text is in the phone's feed index, so the check isn't limited to the excerpt.
3. **The gate passes** if some result has coverage ≥ θ, or contains every anchor.
4. **Otherwise** there is a new path, `not_about`:
   - No answer call is made.
   - The text is a new header (for example, "No announcement seems to be about this. The closest matches:"), then the results list.
   - The strings go through the generator.
   - The path needs an ADR 0004 amendment.

**Choosing θ:**

- Fit θ on replays of the saved e2e34 and Taglish10 runs: saved queries and results, no model calls.
- Pick the largest θ that loses no answerable `answer` path.
- Report the traps and wrong answers it stops.

**Testing:**

- Hand-written vectors written before any replay: anchors only, coverage at θ ± 1 word, Taglish words, and a question that is only stopwords.
- Then the replay, a cold run and a phone run.

**Known limit:** the gate checks aboutness, not correctness. A result can be about the question and still have the wrong answer extracted from it.

## (c) Excerpt length

**Decided order (user, 2026-11-10):**

1. **Centred 500-character window first (zero extra time).**
   - Instead of the first 500 characters, show a 500-code-point window around the first whole-word match of the query (and_v3 match), cut on code points.
   - With no match in the body (a title-only match), keep the first 500.
   - Evidence: flow q08's banned items sit at characters 509–590 of row 56, just past the current cut.
   - **Risk to check:** the deferred `snip_v1` note (fine-tuning plan, 2026-10-31) said a snippet "could expose the long-body trap's hidden fact". The "nothing gets worse" rule on all sets must include that trap. If the centred window loses it, the window is rejected.
2. **Then speed-based length**, only if step 1 is kept or rejected with a recorded reason:
   - Pick L from a fixed ladder {500, 750, 1000, 1500}. L is the largest value whose `predictMs` (the measured answer prompt speed) fits under `BAR_MS` minus a margin, and whose tokens fit under the `n_ctx` limit.
   - The margin is at least the largest observed under-prediction (flow q01: +1.5 s).
   - With an unknown speed (the 200-token rule), L stays 500.
   - Test by replaying at simulated speeds: the Nothing Phone's 138.9 tokens/s and the Redmi's ~27 tokens/s. Count over-budget fallbacks and answer-correct cases per L. Then a phone run to check the predictions at the longer case lengths.

**The excerpt cap is an internal setting now.** Since ADR 0006, the search and the excerpt cut run on the phone over the student's feed (`fakebackend.to_announcement` / assistant-ts). The 500 in the contract's `excerpt` `maxLength` no longer binds Spring.

- **Any change is a versioned assistant setting:** a new named excerpt rule (for example `excerpt_v2_centred`) with its own constant in the generator, and the contract's `maxLength` raised in a new contract version.
- The Python reference, the TS port and the vectors change together, and the version is recorded in each run file.
- Training inputs keep the excerpt rule in force when the data is built (fine-tuning plan, Decision 3). Changing the rule later means rebuilding those inputs.
