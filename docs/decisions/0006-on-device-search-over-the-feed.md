# 0006: The assistant searches on the phone, over the student's feed

- **Status:** PROPOSED (decisions by the user, 2026-11-07; written for acceptance)
- **Date:** 2026-11-07
- **Supersedes:** the Spring parts of the search contract: the "Search contract version 2" and "version 3" requirements on Spring in [`docs/how-it-works.md`](../how-it-works.md), and [0004](0004-model-choice-qwen.md)'s UAT line that Spring runs the matcher. The tool arguments, the result shape and the matcher rules stay. They now run in assistant-ts.
- **When accepted:** update `docs/how-it-works.md` ("Search contract version 3") and ADR 0004's UAT matcher line. and_v3 then runs on the phone in assistant-ts, and Spring needs no search change.

## Context

Read-only reports of the team repos (2026-11-07; nothing was changed there):

- **Mobile API:**
  - `GET /api/v1/announcements` is the feed: Slice pages, size up to 50, with the fields `id`, `title`, `excerpt`, `priority`, `officeName`, `publishedAt`, `pinned`, `read`.
  - `GET /api/v1/announcements/{id}` is the detail: `id`, `title`, `body` (sanitized HTML), `priority`, `officeName`, `publishedAt`, `version`, `attachments`.
  - Auth: `POST /auth/dev-login {email}` returns `{accessToken, tokenType, expiresIn}`; requests carry a Bearer header; a 401 signs the user out.
  - The cache is React Query, in memory, cleared on sign-out (`auth-context.tsx`: `queryClient.clear()`).
- **Spring feed:**
  - It applies all visibility per student: `archived = false`, status `PUBLISHED` or `FOR_DELETION`, academic year `ACTIVE`/`PREVIOUS`, the target role, and year level null or equal to the student's.
  - Sort: pinned, then `publishedAt`, then id, all descending.
  - The feed excerpt is 160 characters, with tags stripped but character references **not** decoded.
  - The `search` parameter is title-only, one `LIKE` phrase.
- **Detail GET:** it writes nothing (verified in the report: a read-only transaction, no listeners, no audit). Marking as read is a separate `POST /announcements/{id}/read`.
- **`publishedAt`** (read in `archways-backend` at `b1b6396`):
  - Both DTOs declare it as `OffsetDateTime`. `AnnouncementFeedMapper.toOffset()` takes the stored `LocalDateTime`, truncates it to seconds, and attaches `Asia/Manila` ("Stored timestamps are Manila local time").
  - With Spring Boot's Jackson defaults (no `spring.jackson.*` settings, no custom `ObjectMapper`), this serializes as ISO-8601 with the offset, for example `2026-11-07T15:33:53+08:00`. **Unverified against a live response.**
  - The stored value is written with `LocalDateTime.now()` (the JVM's default zone; `AnnouncementService`, `AnnouncementPublishScheduler`), not `AppTime`.
  - The Dockerfile pins the JVM to Manila (`TZ=Asia/Manila`, `-Duser.timezone=Asia/Manila`). A local run outside Docker uses the machine's zone.

A new search endpoint would have to repeat every visibility rule of the feed, per student. Searching the feed the student already sees needs no backend change and cannot show anything the feed doesn't.

## Decision (user, 2026-11-07)

1. **The assistant searches on the phone, over exactly the student's feed.**
   - There is no new backend endpoint.
   - The search contract's matching (and_v3, the adopted matcher, with `contracts/search_synonyms_v1.json`) becomes an **assistant-ts matcher**, not a Spring requirement.
   - The `search_announcements` arguments the model writes are unchanged. The app answers them from an in-memory index.
2. **Reversal: `FOR_DELETION` posts are searchable.** This reverses the 2026-11-06 decision ("PUBLISHED only, FOR_DELETION excluded"). The student's feed shows them, and the client cannot tell them apart from published posts.
3. **`year_level` is null for every feed item,** because the feed already filtered by the student's year level.
   - **Consequence:** the model cannot say an announcement is "for 2nd-year students" unless the title or text says so.
   - Under the answer prompt, a null `year_level` reads as "applies to all", and the guard checks only dates and numbers, so this is a wording limit, not an unsafe one.
4. **The assistant never calls the read POST.** Fetching details for the index uses only the detail GET, which writes nothing.

## How it works (to be built; the plan is in the devlog)

- **Index:**
  - Fetch every feed page (size 50), then every detail with limited parallelism.
  - Each body becomes plain text by the contract's rule (`excerpt.py` `plain_text()`, ported): strip tags, decode references, collapse whitespace, then cut to 500.
  - The index lives in memory only and is cleared on sign-out.
- **Search:**
  - and_v3 over the plain-text title and body. This settles the old question of whether to match HTML or plain text: plain text.
  - The days window is applied locally on `publishedAt`.
  - Order: newest first, then id; pinned is ignored. Then the limit.
- **Row mapping:**
  - `id`: the feed id as a string.
  - `title`, `excerpt`: the plain text, cut to 500.
  - `office`: `officeName`.
  - `priority`.
  - `year_level`: null.
  - `posted_at`: `publishedAt`, which must carry an offset. An item without a usable `publishedAt` is left out of the index and counted in the log.

## Consequences

- **Spring needs no search change.** The v2/v3 search vectors become assistant-ts parity vectors (Python reference against TS, on Node and Hermes).
- **`CLAUDE.md` has a rule this ADR changes:** "Only PUBLISHED, non-archived announcements may reach the model. Filter with an allowlist in the Spring query, never in the prompt." Under this ADR, the allowlist is the feed's own visibility filter, and `FOR_DELETION` posts can reach the model. **The user should update that rule** (it is the user's file).
- **Time:**
  - The adapter trusts the API's offset.
  - This is correct only if the server's JVM ran on Manila time when `publishedAt` was written. Docker guarantees it; a local run outside Docker on a non-Manila clock does not. The time-zone check is still open.
- **Cost and freshness:**
  - The phone downloads every detail it indexes. The fetch and index times are logged so this can be measured.
  - The rebuild and edit-detection rules are in the plan.
- **Privacy:** announcement text stays on the phone, in memory, and is cleared on sign-out. Nothing is written to disk.

## Unverified

- The exact JSON text of `publishedAt` from a live server (the Jackson defaults are assumed).
- Whether body edits can happen in place on a live row. Approved edits create a new row and archive the parent (`AnnouncementService`), so a changed id set catches those.
- llama.rn 0.13.0-rc.8 on the mobile app's stack. `archways-mobile` `package.json` lists `expo ^44.0.6` and `react-native ^0.72.17`; the Gate 1 test app runs Expo 57 and React Native 0.86.
