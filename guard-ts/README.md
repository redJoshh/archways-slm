# guard-ts

The answer guard for the Archways assistant, ported to TypeScript so the mobile app can run it on the device. It is a port of `guard()` in `src/archways_assistant/e2escore.py`. It has zero runtime dependencies and reads no clock and no I/O.

```ts
import { guard, fallback, LAST_RESORT_MESSAGE } from "./guard-ts/src/guard.ts";

let text: string;
try {
  text = guard(reply, results, question, forbidden).text;
} catch {
  // Defense in depth: the guard should never throw on contract-valid
  // input, but if it does, never show the unchecked model reply.
  try {
    text = fallback(results);
  } catch {
    text = LAST_RESORT_MESSAGE;
  }
}
```

- `results`: the `search_announcements` results, exactly as Spring returns them (the contract's `$defs/result`).
- `forbidden`: the titles of rows that must never reach the model. On the device this is normally `[]`, because Spring already filters those rows out.
- The return value is `{ text, fired, codes, reasons }`. Show `text`.

**Always wrap the guard in try/catch, as above.**

## Parity with the Python guard

`tests/vectors/guard_vectors.json` holds:
- the guard's unit-test cases
- edge cases
- phone replies
- every reply in the saved probe runs.

Python and TypeScript must agree on `fired`, `codes` and `text` for every vector. `reasons` is for people and may differ.

The guard's behaviour is an explicit spec, not either language's regex quirks:
- Matching is ASCII only: `\d` is 0-9, `\s` is `[ \t\n\r\f\v]`, `\b` is ASCII, and month names fold ASCII case only.
- Before claims are read, the characters in `GUARD_SPACES` (`src/spec.ts`) become spaces. The text shown never changes.
- A reply with a decimal digit outside 0-9 (`NON_ASCII_DIGIT_RANGES`) fires the guard.
- `posted_at` must be in the contract's RFC 3339 format. Otherwise `fallback()` throws, and a fired guard returns `LAST_RESORT_MESSAGE`.

**Documented gaps.** These inputs are outside the parity domain:
- **Lowercasing for `forbidden`.** It is plain `toLowerCase()` vs Python's `str.lower()`. They can differ on exotic text (e.g. İ, final sigma, newer Unicode).
- **Lone surrogates.**
- **Results that don't match the contract** (missing keys, non-strings).
- **Numbers longer than 4,300 digits.** Python's `int()` raises on them; TypeScript does not.

## Commands

```sh
cd guard-ts
npm ci
npm test              # tsc, then node --test over every vector
npm run test:hermes   # the same vectors under the Hermes 0.12 CLI (smoke test)
```

`GUARD_VECTORS=<path>` points either command at another copy of the vector file.

## Changing the guard

Any guard change updates both versions and the vectors, in one change:
1. Change `src/archways_assistant/e2escore.py` and its unit tests.
2. Run `uv run python scripts/export_guard_vectors.py --refresh`, or run it without `--refresh` on a machine that has `runs/`.
3. Change `guard-ts/` to match.
4. Run `uv run pytest` and `cd guard-ts && npm test`. Both must pass.

The mobile app copies or imports `guard-ts/`, so it must take the new version too.

The vectors hold dev questions and seed data only. They are test data. Never use them as prompts or training data.
