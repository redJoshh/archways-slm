# Integration guide: the Archways assistant in `archways-mobile`

- **Status:** FROZEN 2026-11-17. It replaces the 2026-11-10 draft, which lived in a chat reply, not a file. Its 7 milestones are kept and updated below.
- **Vendor source:** archways-assistant `830dcfd` (`830dcfd` and later docs-only commits have the same `assistant-ts/` and `guard-ts/`). Record the full hash in `vendor/archways/VENDORED.md`.
- **Backend checked against:** `archways-backend` `origin/main` `a823988` (read-only, 2026-11-17).
- **Mobile app checked against:** `archways-mobile` `origin/main` `b43ffdc` (expo `~57.0.30`, react-native `0.86.3`, expo-router, axios).
- **Decisions behind it:** [ADR 0004](../decisions/0004-model-choice-qwen.md), [0005](../decisions/0005-gate-1-cold-definition.md), [0006](../decisions/0006-on-device-search-over-the-feed.md), [0007](../decisions/0007-no-training-and-held-out-protocol.md); the parts and their API: [`assistant-ts/README.md`](../../assistant-ts/README.md).

If this guide and the README disagree, this guide wins. The README's first example (search through a Spring endpoint) predates ADR 0006: the assistant searches the student's own feed on the phone.

---

## 1. What ships

**The shipped assistant = the evaluated FINAL configuration + window_v1** (ADR 0006 and ADR 0007 amendments, 2026-11-17).

| Part | Value | Where it's set |
|---|---|---|
| Model | qwen3:0.6b, Q4_K_M GGUF, untuned (no training, ADR 0007) | the model file (section 4) |
| Query prompt | v1 | `generated.ts` (`QUERY_PROMPT_*`) |
| Answer prompt | v1 | `generated.ts` (`ANSWER_PROMPT_*`) |
| Search matcher | and_v4 | `PHONE_MATCHER` → `makeFeedSearch()` default |
| Ranking | rank_v1 (by the raw question) | `PHONE_RANK` |
| Not-found stripping | strip_nf_v1 | `PHONE_STRIP_NF` → `askAssistant()` default |
| Window fallback | window_v1: after 0 results at `days` 30, the same search over 365 days | `PHONE_FALLBACK` (outside FINAL, `archways_assistant/phone.py`) |
| Off | retry_v1, gate_v1, excerpt_v2_centred, answer prompt v4 | `PHONE_RETRY` / `PHONE_EXCERPT` = null |

- **Use the defaults:** call `makeFeedSearch(index)` and `runtime.ask(...)` with no configuration arguments. Every value above is a generated default. Never pass other values in the app.
- **window_v1** can't change any dev or held-out result at the evaluation dates. It changes behaviour from about 2026-12-07, when the 2026-11-06/07 snapshot rows leave the 30-day window; that is its purpose. Checked on the Nothing Phone at a simulated 2026-12-10: 13/13 result ids as at the real date (devlog 2026-11-17).
- **Never copy the test app's DEV-ONLY "simulate date" field** (`gate1-llm` `LiveTest.tsx`) into `archways-mobile`. The app always passes `nowMs: Date.now`.

## 2. Backend contract (re-verified on `a823988`)

The assistant uses only the student's own feed through the existing API. **Spring needs no change.**

| Call | Use | Notes |
|---|---|---|
| `GET /api/v1/announcements?page=P&size=50` | list the feed | `SliceResponse {content, page, size, hasNext}`. Sort: pinned, publishedAt, id, DESC. Size max 50. |
| `GET /api/v1/announcements/{id}` | one detail per item | Read-only transaction, SELECTs only (including the revision-chain CTE). **Writes nothing.** |

- **Never call `POST /{id}/read`, `PUT /{id}/bookmark` or `DELETE /{id}/bookmark` from the assistant.** They are the only writes on this resource. The index must not mark anything read or bookmarked.
- **Visibility (`MOBILE_VISIBLE`, unchanged):**
  - `archived = false`
  - status `PUBLISHED` or `FOR_DELETION`
  - academic year `ACTIVE` or `PREVIOUS`
  - the student's target role
  - year level NULL or matching
- The feed is the allowlist (ADR 0006). The app never adds rows from anywhere else.
- **NEW, detail forwarding:**
  - A detail GET for an id that is no longer visible (an approved edit archived it) forwards to the newest visible revision.
  - It returns **that** revision's id: a different id and a new version, with a plain 200 and no marker.
  - **Handled** (`830dcfd`): `createFeedIndex` stores the detail under the **response** id and drops the requested id. If that id is already indexed it keeps one row, and it counts each case in the index report's `forwarded`.
  - A revision the feed didn't list is fetched again at the next refresh.
  - Tests: `assistant-ts/test/feedIndex.test.ts`.
- **NEW, `bookmarked`:** both DTOs gained a trailing `bookmarked` boolean; no field was removed or renamed.
  - **Handled:** pages and details ignore unknown fields, and still require the fields they use (`id`, `title`, `body`, `publishedAt`).
  - Pinned by feed vectors (3 rows with `bookmarked` and an unknown nested field) on Node and Hermes, and by an index test.
- **`publishedAt`:** the conversion code is unchanged since `b1b6396`. Live responses on 2026-11-10 and 2026-11-17 carried `+08:00` (seen on the device).
  - A value without an offset is read as Manila time, and the row is counted in `offsetAdded`.
  - Run the server under Docker (Manila clock), as ADR 0006 requires.
- **`dev-login`** is still `@Profile("dev")` only. The production app never calls it.

## 3. How the assistant behaves (what the app wires, not re-implements)

```
question → [wait while "getting ready"] → query call → feed search (index, rank_v1, and_v4, window_v1)
        → budget check → answer call → guard → strip_nf_v1 → label + reply + results list
```

- **One serial model queue** (`queue.ts`, through `createAssistantRuntime`): every model call and token count goes through it. llama.rn runs one completion at a time; a query during priming failed on the Redmi 10C (118 ms).
- **Readiness:**
  - Priming and the re-measure are exclusive jobs. A question asked meanwhile **waits** (`whenReady`) instead of failing.
  - The wait is `readyWaitMs` in the UAT log, and it isn't counted in the budget.
  - Show "getting ready" while `runtime.state()` is `"priming"` or `"measuring"`. **Expect up to ~30 s on budget phones and ~5 s on mid-range ones.**
  - A question asked before the model has even loaded waits for the load, in the app.
- **The adaptive time budget** (ADR 0004):
  - Before the answer call it predicts the whole question's time from the measured **answer-call** speeds (prompt and generation rates from answer priming and answer calls; query calls have their own speed, which the budget never reads).
  - If the prediction exceeds 15 s it skips the answer call and shows the results list. Without a known speed, the 200-token rule applies; the `n_ctx` limit always applies.
  - Don't add an app timeout under 15 s around a question.
- **Re-measure:** after priming and after each question, if the answer generation rate is unknown or below 0.6 × the query's, one exclusive measuring call runs, at most 2 per Manila day.
- **What the student sees** (`result.text` only, never anything else):
  - **`answer`:** the label "AI answer, please check the announcements below.", the model's reply (after the guard and strip_nf_v1), then the **results list**.
  - **Every other path with results** (not found by the model, guard fired, over budget, answer error): the results list only.
  - **No results:** "No official announcement was found for your question."
  - **Errors before a search:** the last-resort message.
  - The list is "These announcements may help:", then one line per result with its title and posted date.
- **Paths:** the full table is in `assistant-ts/README.md` ("Use"). Every path returns text; `askAssistant()` never rejects.
- **Index (`createFeedIndex`):**
  - **Builds:** a full build every 60 min (all pages, then details, 4 at a time); a refresh after 10 min (pages, then new, changed or forwarded ids).
  - **Errors:** 404 details are skipped; any other error keeps the previous index.
  - **Clearing:** `clear()` on sign-out and on 401.
  - **Logging:** reports are numbers only (pages, items, details, removed, skipped, offsetAdded, forwarded, rows, timings).

## 4. Decisions recorded (user, 2026-11-17)

- **Model hosting:**
  - A **public GitHub release asset**, with the Apache-2.0 licence text attached.
  - **Versioned file name**, for example `qwen3-0.6b-q4_k_m-v1.gguf`; a new version is a new name.
  - **On update** the app deletes the old file after the new one is verified.
  - The repository and release URL are for the team to create (unverified).
- **The file:**
  - Ollama blob `sha256-7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa`, **522,640,096 bytes** (about 523 MB).
  - **MD5 `3def07fb2d88a5846fe5accf72c4297c`**, SHA-256 `7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa`. Both were computed on the development laptop on 2026-11-17 from that blob.
- **Checksum: MD5 via expo-file-system (native)** for download integrity.
  - The release notes publish both MD5 and SHA-256. HTTPS from GitHub covers tampering. Together these satisfy "verified by checksum".
  - The app compares the downloaded file's MD5 with a constant in the app.
  - The SHA-256 stays a constant too: session file names include it (`session.ts` `modelSha256`).
  - **SDK 57 API** (docs read 2026-11-17):
    - **New API** (`expo-file-system`): `File#md5` (`string | null`, read synchronously). The page shows an odd deprecation note on it, so confirm on the live page before relying on it.
    - **Legacy** (`expo-file-system/legacy`): `getInfoAsync(uri, { md5: true })` → `FileInfo.md5`.
    - expo-file-system has no SHA-256. This replaces the README's "verify the SHA-256" line.
- **Platform:** UAT is **Android only** (an explicit scope decision). iOS is untested.
- **Sign-in:** UAT uses **real student Google sign-in**. `test.*` accounts are only for the demo login (`EXPO_PUBLIC_DEMO_LOGIN_ENABLED`).
- **Entry point and flag:**
  - **Entry point:** a **Home header button** opens the Ask screen.
  - **Build-time flag:** `EXPO_PUBLIC_ASSISTANT_ENABLED`.
  - **Opt-in:** an **in-app switch in Settings**.
  - The assistant exists only if both are on; otherwise nothing is loaded, downloaded or shown.

## 5. Milestones (each accepted on a phone)

### M1: Development build and parity vectors on the phone

- **Dependencies:**
  - install `llama.rn@0.13.0-rc.8` (exact pin) and `expo-file-system` (with `npx expo install`)
  - the llama.rn config plugin
  - the `eas-build-post-install` script (`node ./node_modules/llama.rn/install/download-native-artifacts.js`)
  - `arm64-v8a` in `eas.json`
- **TypeScript and lint:** `allowImportingTsExtensions`; ignore `vendor/**` in lint.
- **Vendor:** copy `assistant-ts/src/*.ts` and `guard-ts/src/*.ts` from **`830dcfd`** into `vendor/archways/`, in the same layout, with `git show` (the committed bytes). Record the hash in `VENDORED.md`. **Never edit vendored files**; re-vendor instead.
- **Vector screen:** a dev-only screen runs the guard, assistant, feed and window_v1 vectors. The vector JSON files and `*Vectors.ts` runners stay out of preview builds.
- **Rebuild:** `eas build --profile development`.
- **Note:** on Windows, run `npm ci` / `npm install` from PowerShell. Under Git Bash, GNU tar fails on llama.rn's native-artifact download (`C:` read as a host; devlog 2026-11-17).
- **Accept:**
  - the dev build starts
  - **all vectors pass on the Redmi under Hermes**
  - a signed-out start and Expo Go don't crash (assistant hidden)

### M2: Model download

- **Download:**
  - from the GitHub release asset, resumable, into the app's **document directory** (`Paths.document`; legacy `documentDirectory`)
  - a free-space check first (`Paths.availableDiskSpace`)
  - progress shown
  - a Wi-Fi notice before 523 MB
- **Resume:** `File.createDownloadTask(...)` → `DownloadTask` (`pauseAsync`/`resumeAsync`/`savable`), or legacy `createDownloadResumable`. Check against the SDK 57 page.
- **Verify:**
  - MD5 once after the download, then write a "verified" marker
  - on a mismatch, delete and download again
  - delete the old versioned file after a new one is verified
- **Settings:** "Delete assistant model".
- **Accept:**
  - an interrupted download resumes
  - a truncated file is detected and re-downloaded
  - **the MD5 verify time on the Redmi is recorded**
  - about 523 MB on disk, never duplicated (one versioned file)

### M3: Background load and priming

- **Where:** an assistant provider in `src/app/_layout.tsx`, inside `AuthProvider`.
- **When:**
  - **signed in + flag on + opted in + model verified:** `initLlama({ n_ctx: 2048, n_threads: 4, n_gpu_layers: 0, use_mmap: true, use_mlock: false })`, then `createAssistantRuntime`, then `runtime.prime(Date.now())`, not awaited.
  - **At sign-in, in the background, never on the first question.**
  - Re-prime on a new Manila day when the app becomes active.
  - Never at module scope: the FCM background handler loads modules without a UI.
- **Session files:** use a real file-exists check. **Delete session files of other dates and other model versions** after priming: only today's query and answer files remain.
- **Accept:**
  - the first question never pays for load or priming (it shows "getting ready" and waits)
  - cold load and priming times are logged (numbers only)
  - session files survive a restart (record their size on disk)
  - **session-file cleanup:** after priming on a second day, or after a model update, only the current day's two files exist

### M4: Feed index

- **Wiring:**
  - `fetchJson = (path) => api.get(path).then((r) => r.data)` over the existing axios client (its base URL ends in `/api/v1`)
  - axios errors are rethrown as `HttpError(error.response?.status ?? 0)`
  - `createFeedIndex(fetchJson, { activity: runtime.beginActivity, log })`
- **Lifecycle:**
  - `ensure()` when the Ask screen opens
  - `clear()` through `addBeforeSignOut` (`auth-context.tsx`) and on a 401
- **Behaviour:** forwarded details and extra fields are handled by the vendored code (section 2). Log the reports (numbers only).
- **Accept:**
  - index rows = the feed count for the test account
  - **no POST, read or bookmark request in the server log**
  - signing out and then in as another student shows none of the first student's rows
  - after an approved edit between list and detail, the revision appears once under its new id (`forwarded` ≥ 1 in the log)

### M5: Ask screen

- **Route:** `src/app/assistant.tsx` in the `signedIn` block, opened from the Home header button. Hidden unless the flag is on and the student opted in.
- **Behaviour:**
  - input of at most 500 code points
  - show **only `result.text`**
  - **search:** `makeFeedSearch(index)` with its defaults (FINAL + window_v1); `nowMs: Date.now`
  - no app timeout under 15 s
- **UI:** theme tokens and shared UI components. States for loading, getting ready (`runtime.state()`), error and empty.
- **Privacy line** on the screen: "Your questions are processed on this phone and never sent to the server."
- **Accept:**
  - every README path shows the right text
  - the AI label appears only on `answer`, above the reply, with the list below
  - list items open `/announcement/[id]`
  - tap targets ≥ 44 with accessibility labels

### M6: UAT log

- **What to keep:** append each `QuestionLog` entry to a file. Its fields are `path`, `rule`, `predictedMs`, `actualMs`, `resultCount`, `caseTokens` and `readyWaitMs`.
  - The draft's `totalMs` isn't a field. If wanted, the app computes `actualMs + readyWaitMs`.
  - **Never** log the question or announcement text.
- **Index reports:** log them too (numbers only, including `forwarded`).
- **Export:** Settings → "Export UAT log".
- **Failures:** logging errors never change what the student sees.
- **Accept:**
  - 10 questions → 10 entries
  - no question or announcement text in the file or in logcat

### M7: Preview build

- **Build:**
  - the flag and the model URL, MD5 and SHA-256 values in `eas.json`'s preview env
  - `eas build --profile preview`
  - no vector screen
- **Legal pages:** add the open-source notices in `src/app/legal/[slug].tsx`:
  - **Qwen3 (Apache-2.0)**, with the licence text
  - **llama.cpp (MIT)**, through llama.rn
- **Accept:**
  - Google sign-in against the HTTPS server, then download → prime → ask works on **both** phones (a budget phone and a mid-range one)
  - **llama.rn reports timings in a release build** (otherwise the budget stays on the 200-token rule)
  - the legal pages show both notices

## 6. Notes for testers

- **Battery and heat:** the first download (523 MB), priming and every question run the CPU hard. Phones get warm, and battery drains faster during a session. Test on a charger where possible, and report heat or throttling with the phone model.
- **Getting ready:** after sign-in, and on the first use of each day, the assistant primes for up to ~30 s on budget phones (~5 s on mid-range). Questions asked meanwhile wait; they don't fail.
- **Every AI answer is labelled.** Testers should check it against the listed announcements, which are the source.

## 7. Known limitations (from the held-out final, 2026-11-17, and phone runs)

- **False "not found":** the largest failure. The model says it found nothing although a matching announcement is in the results (held-out: 8 of 16 answerable questions on that path). It is a model-capacity limit, so prompt changes didn't fix it. **Mitigation:** the results list is shown on every path with results.
- **Contradiction on yes/no questions:** one held-out AI answer said something is allowed where its source prohibits it. Same type as at the baseline, unchanged by any fix. The automatic scorer can't detect it.
- **Past-date framing:** a past event can be stated in the present tense (for example "is held" for an August date). The date itself is correct.
- **Budget phones mostly show lists:** on slow phones the time budget skips the answer call more often (Redmi 10C replay, README: e2e-004 predicted 13.9 s and answers; e2e-009 predicted 21.7 s and falls back). The student sees the results list instead of an AI answer.
- **Phone vs laptop runtime:** llama.rn on the phone and Ollama on the laptop can differ on the same prompt. At a simulated 2026-12-10, one flow question gave an AI answer on the phone and the list on Ollama. Evaluation numbers come from Ollama.
- **window_v1 can surface old rows** when nothing in the last 30 days matches. The list shows each row's posted date.
- **Held-out numbers** (human-reviewed): helpful 13/16, AI correct 3/6, unsafe 1/20. That set is closed; any later change is a v2 on a new held-out set (ADR 0007).

## 8. Never

- Never call the read POST or the bookmark PUT/DELETE, or any endpoint other than the two GETs in section 2.
- Never send a question or announcement text to the server, analytics or logs.
- Never edit vendored files, `generated.ts` or the prompts in the app. Re-vendor from archways-assistant.
- Never pass non-default configuration to `makeFeedSearch` / `askAssistant`. Never copy the DEV-ONLY simulate-date field.
- Never load the model or prime at module scope, or on the first question.
