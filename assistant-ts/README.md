# assistant-ts

The on-device assistant flow for the Archways mobile app: the UAT configuration of [ADR 0004](../docs/decisions/0004-model-choice-qwen.md), ported to TypeScript.

The UAT configuration:
- untuned qwen3:0.6b
- query prompt v1 and answer prompt v1
- the guard (from [guard-ts](../guard-ts))
- the budget fallback

The port follows `src/archways_assistant/assistant.py`. It has **zero runtime dependencies**: it imports guard-ts by relative path and never imports llama.rn. It reads no I/O; the app passes in everything that touches the outside world.

```
question -> query call -> search (Spring) -> budget check -> answer call -> guard -> text
```

## Use

```ts
import { askAssistant, makeComplete, primeSessions } from "./assistant-ts/src/index.ts";

const settings = {
  dir: permanentModelDir,          // not a cache the OS may clear
  modelSha256: MODEL_SHA256,       // the GGUF's checksum, verified at download
  llamaRnVersion: "0.13.0-rc.8",
  nCtx: 2048,
  nThreads: 4,
};
const llama = {
  countTokens: async (text) => (await ctx.tokenize(text)).tokens.length,
  completion: async (prompt, nPredict) =>
    (await ctx.completion({ prompt, n_predict: nPredict, temperature: 0, top_k: 1, top_p: 1, seed: 42,
                            stop: ["<|im_end|>", "<|im_start|>"] })).text,
  saveSession: (path, tokenSize) => ctx.saveSession(path, { tokenSize }),
  loadSession: async (path) => (await ctx.loadSession(path)).tokens_loaded,
  fileExists: (path) => FileSystem.getInfoAsync(path).then((info) => info.exists),
};

// On app start, and when the app returns to the foreground on a new Manila day:
await primeSessions(llama, settings, Date.now());   // about 30 s on the Redmi 10C; show progress

const result = await askAssistant(question, {
  nowMs: Date.now,
  complete: makeComplete(llama, settings),
  search: (args) => api.post("/…/search_announcements", args).then((r) => r.data),  // Spring; path TBD
  countTokens: llama.countTokens,
});
show(result.text);   // only result.text; log result.path and result.timings, never the question
```

`askAssistant()` never rejects, and every path returns text to show. The model's text is shown only after the guard has passed it.

| `path` | When | Text shown |
|---|---|---|
| `answer` | The guard passed the reply | The reply (ASCII whitespace trimmed) |
| `guard_fired` | The guard rejected the reply | The guard's fallback (titles and posted dates) |
| `budget_fallback` | The answer case part is over 200 Qwen tokens: **no answer call** | `fallback(results)` |
| `answer_error` | Token counting, the answer call or the guard threw | `fallback(results)` |
| `not_found` | Valid search, no results: no answer call | `NOT_FOUND_MESSAGE` |
| `query_invalid` | The query reply isn't valid search arguments | `LAST_RESORT_MESSAGE` |
| `query_error` | The query call threw | `LAST_RESORT_MESSAGE` |
| `search_error` | The search threw, or broke the result contract | `LAST_RESORT_MESSAGE` |
| `question_invalid` | Empty, whitespace-only, over 500 code points, or lone surrogates | `LAST_RESORT_MESSAGE` |

If `fallback()` itself fails, the text is `LAST_RESORT_MESSAGE`. Put the timeout in `complete`/`search` (reject on timeout); the flow falls back as above.

**Decision to confirm:** an invalid query reply shows `LAST_RESORT_MESSAGE`, not the not-found message. The probe scores it as not found, but "not found" would be untrue when the model failed. qwen3:0.6b had 0/34 invalid on dev.

## What is in here

**`render.ts`: the Qwen prompts for both calls.** A port of `render_qwen3()`. It sends exactly what Ollama sends with `"think": false`:

```
<|im_start|>system\n\n{system}<|im_end|>\n        systemTurn(): cached in a session file
<|im_start|>user\n{user} /no_think<|im_end|>\n    casePart(): processed per question
<|im_start|>assistant\n<think>\n\n</think>\n\n
```

- There is no start-of-text token.
- The prompt is sent as a **raw `prompt`**, never through llama.rn's messages or jinja formatting.
- `{today}` is the Manila date (fixed UTC+08:00) with English weekday names.
- The answer call's results are serialized exactly like the probe's `announcements_message()`: JSON with indent 1, in the contract's key order whatever order Spring sends, with `<` written as `\u003c`.

**`contract.ts`: query-reply parsing and validation** against `contracts/search_announcements.schema.json`.

The query reply must be strict JSON for the whole text. JSON whitespace around it is allowed; code fences and prose are rejected.

The arguments must be an object with only these keys:
- `query`: 1–200 code points, well-formed Unicode, and at least one character that is not ECMA-262 whitespace (the schema's `\S`)
- `days`: 1–30, a JSON number with an integral value (`30.0` counts)
- `limit`: 1–10, the same

Defaults are not filled in; Spring applies them.

Results are checked before they reach the model. A result must have exactly the 7 contract keys, string fields, title ≤ 255 and excerpt ≤ 500 code points, `year_level` an integer or null, and a `posted_at` the guard can read. There are at most 10 results.

**The budget check: exact Qwen tokens, through llama.rn `tokenize()`.**
- llama.rn 0.13.0-rc.8's `tokenize()` calls `common_tokenize(ctx, text, add_special=false, parse_special=true)` (`cpp/rn-llama.cpp:828`). It is the model's own tokenizer, it adds nothing, and it reads `<|im_start|>` and friends as single special tokens, as in the prompt.
- On the Redmi 10C, llama.rn counted 591 tokens for e2e-009's answer prompt, the same as Ollama.
- The case part begins with the `<|im_start|>` special token, so the system turn and the case part tokenize independently. Measured on Ollama 0.40.14 over all 47 vector prompts: system turn (197) + case part = whole prompt, every time.
- **A byte-count proxy doesn't work at this budget.**
  - Over the same 47 case parts, UTF-8 bytes per Qwen token ranged from 2.28 to 4.45 (median 3.23).
  - A safe proxy for 200 tokens would cap at about 456 bytes. Almost every one-row case part (482 bytes and up) would then go to the fallback.
  - So the flow needs `countTokens`. If it throws, the reply is the no-model fallback.

**`session.ts`: session-file priming** ([ADR 0005](../docs/decisions/0005-gate-1-cold-definition.md)).
- **Prefixes:** the query and answer system turns. Their token counts are 213 and 197 on a Monday on Ollama; they vary with the weekday name, so they are always counted, never hard-coded.
- **File names** encode the call kind, the prompt SHA-256, the Manila date, the model SHA-256, the llama.rn version, `n_ctx` and threads.
- **Rebuild them:**
  - every Manila day, because both v1 prompts contain today's date
  - after any change to the model, a prompt, llama.rn or those settings (each gives a new file name)
  - when a load returns the wrong token count (`makeComplete` re-primes once, then fails, and the flow falls back)
- **Priming:** run `prefix + casePart("")` with `n_predict` 1, then `saveSession(file, { tokenSize: tokens(prefix) })`. The Gate 1 app did the same with a real question as the user turn.
  - Measured on the Redmi 10C: 22.0 s (answer) + 7.7 s (query), once per day.
- **Per question:** load the query session, then the query call (`n_predict` 64); load the answer session, then the answer call (`n_predict` 200). The 64 and 200 are the Gate 1 app's values. Session loads measured 0.1–0.2 s.

## Parity with Python

`tests/vectors/assistant_vectors.json` comes from `scripts/export_assistant_vectors.py`, and `tests/test_assistant.py` checks it against the Python reference, the probe and the contract. It holds:
- today's date for instants around midnight
- the query and answer prompts for every e2e and Taglish dev case, plus edge rows
- 47 query replies
- 28 result arrays
- 24 scripted questions covering every path

`generated.ts` (the prompt texts and their SHA-256, contract bounds, messages) comes from `scripts/export_assistant_ts.py`. **Never edit it by hand.** Python and TypeScript must agree on every vector.

**Documented gaps.** The spec (ECMA-262 `\S`, well-formed Unicode) differs from Python's `jsonschema` on these queries:
- U+0085 alone and U+001C alone are valid here
- U+FEFF alone and a lone surrogate are invalid here

`tests/test_assistant.py` lists them. Spring's own Java validation may differ again on such inputs; unverified.

## Commands

```sh
cd assistant-ts
npm ci
npm test              # tsc, then node --test (vectors, flow driver, session priming with a fake llama)
npm run test:hermes   # the vectors and one askAssistant() run under the Hermes 0.12 CLI (smoke test)
```

```sh
uv run python scripts/export_assistant_ts.py        # after a prompt or contract change; --check to verify
uv run python scripts/export_assistant_vectors.py   # after a reference change; --check to verify
```

## What the mobile app must do

- **Model file:** qwen3:0.6b, Q4_K_M GGUF.
  - This is the Ollama blob `sha256-7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa`: 522,640,096 bytes, 751.63M parameters. The blob is content-addressed, so its SHA-256 is the name. That it is byte-identical to what the phone loaded in Gate 1 is unverified.
  - Download it once into **permanent** app storage. The Gate 1 app's copy-on-pick filled about 2 GB.
  - Verify the SHA-256 before the first load; delete and re-download on a mismatch; resume on a bad network.
  - Where it is hosted is for the team to decide (unverified).
- **llama.rn 0.13.0-rc.8, pinned exactly** (a release candidate; the version measured):
  - `initLlama({ n_ctx: 2048, n_threads: 4, n_gpu_layers: 0, use_mmap: true, use_mlock: false })`
  - **No parallel mode:** `saveSession`/`loadSession` throw in it.
  - Completion: a raw `prompt`; `temperature: 0`, `stop: ["<|im_end|>", "<|im_start|>"]`.
    - The Gate 1 app set only `temperature: 0`. Adding `top_k: 1`, `top_p: 1` and `seed: 42` (as in the evaluation) is a proposal; whether it changes phone replies is unverified.
  - No JSON grammar in UAT: none was used on the phone, and Ollama gave the same e2e-009 query reply with or without the schema.
- **Priming:** on first use each Manila day, with a progress message (about 30 s, apart from model load: 1.0–2.5 s measured).
- **One context, kept loaded.** With `use_mmap`, the app survived being swapped out and still answered (Gate 1, development build).
- **Licence:** ship the Apache License 2.0 text and notices for qwen3:0.6b.
- **Logging:** paths and timings only, never questions or replies (no real user data in logs).

## What Spring must do

- **Search contract v2:**
  - `and_v2` matching with `contracts/search_synonyms_v1.json`
  - pass `tests/vectors/search_vectors_and_v2.json`
  - the same ILIKE escaping (`ilike_pattern()` in `fakebackend.py`)
- **An allowlist in the query:** only PUBLISHED, non-archived, visible rows. Never filter in the prompt.
- Apply the defaults (`days` 7, `limit` 5), and reject invalid arguments per the schema.
- Return `$defs/result`:
  - excerpt ≤ 500 characters
  - `posted_at` in RFC 3339 with the `+08:00` offset
  - newest first, at most `limit` rows
- The endpoint path and its auth are not defined in this repo (unverified; team).

## Unverified

- **The budget fallback rate on real announcements.** The 200-token rule was calibrated on seed rows, 24 of 25 of which are under 500 characters. It must be measured before UAT.
- `tokenize()` on the Redmi 10C: its time, and that it returns 394 for e2e-009's case part. One phone check.
- Priming with an empty user turn: the Gate 1 app primed with a real question.
- Whether session files survive app restarts, and their size on disk.
- A release build (every phone run used a development build), memory with other apps open (about 1.0 GB PSS measured), and iOS.
- That 500 code points is a good question limit (a proposal; it keeps a pasted text from overflowing `n_ctx` 2048).
