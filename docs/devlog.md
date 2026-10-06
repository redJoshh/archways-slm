# Devlog

Development history for archways-assistant. Newest entries first.
Add new entries at the top of the log. Never rewrite or delete past entries; correct mistakes with a new entry.
Write "unverified" for anything git history or the repo files don't show.

Template:

```markdown
## YYYY-MM-DD: <short title>

- **Date:** YYYY-MM-DD (HH:MM–HH:MM +08:00)
- **What changed:**
- **Why:**
- **How it was verified:** `<exact command>` → `<result>`
- **Commits:**
- **Open questions / next:**
```

---

## 2026-10-06: Devlog and logging rules

- **Date:** 2026-10-06
- **What changed:** Added `docs/devlog.md`, with entries backfilled from `git log` and the repo files. Added a `## Devlog` section with four logging rules to `CLAUDE.md`.
- **Why:** To keep a dated development history that doesn't depend on chat context.
- **How it was verified:**
  - `uv run pytest -q` → `44 passed in 0.16s`
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `4 files already formatted`
- **Commits:** the commit that adds this file (`docs: add devlog and logging rules`)
- **Open questions / next:** See the open questions in the entries below.

## 2026-10-06: search_announcements tool contract and tests

- **Date:** 2026-10-06 (15:46–15:47 +08:00)
- **What changed:**
  - Added `jsonschema` and `rfc3339-validator` to the dev dependency group (`pyproject.toml`, `uv.lock`).
  - Added `contracts/search_announcements.schema.json` (draft 2020-12, `$id` `urn:archways:tool:search-announcements:v1`):
    - `$defs/arguments`: `query` (required, 1–200 chars, must contain a non-whitespace character), `days` (1–30, default 7) and `limit` (1–10, default 5). No `$ref`; `additionalProperties: false`.
    - `$defs/announcement`: `id`, `title` (≤255), `excerpt` (≤500), `office`, `priority`, `year_level` (integer or null) and `posted_at` (date-time). All are required; `additionalProperties: false`.
    - `$defs/result`: an array of announcements, at most 10.
  - Added `tests/test_search_announcements_schema.py` with 44 test cases covering valid and invalid arguments and results.
  - Added two rules to `CLAUDE.md`: only PUBLISHED, non-archived announcements may reach the model; Spring applies tool-argument defaults.
- **Why:** The model emits `search_announcements` tool calls that the Spring app executes (`CLAUDE.md`), so both sides need a shared, testable contract. The `$id` is versioned so a breaking change becomes v2 (`$comment` in the schema). Descriptions are written for the model; implementation notes go in `$comment`.
- **How it was verified:** Rerun on 2026-10-06 while writing this entry:
  - `uv run pytest -q` → `44 passed in 0.16s`
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `4 files already formatted`
- **Commits:** `94f5db5`, `5fc60fb`, `191fbfd`, `d3c9faa`
- **Open questions / next:**
  - `priority` is a plain string; it could become an `enum` once the allowed values are known.
  - The Spring app still has to apply the argument defaults and the PUBLISHED/non-archived allowlist. Its repo is separate, so this is unverified from here.

## 2026-10-06: Pin Python 3.12

- **Date:** 2026-10-06 (15:28 +08:00)
- **What changed:** Changed `.python-version` from `3.14` to `3.12`, changed `requires-python` in `pyproject.toml` from `>=3.14` to `>=3.12`, and updated `uv.lock` to match.
- **Why:** The new version matches the "Python 3.12, managed by uv" rule in `CLAUDE.md`. Why 3.14 was chosen first: unverified.
- **How it was verified:** unverified. Git history has no record of a test run.
- **Commits:** `7b1de36`
- **Open questions / next:** none recorded.

## 2026-10-06: Add CLAUDE.md

- **Date:** 2026-10-06 (15:11 +08:00)
- **What changed:** Added `CLAUDE.md` (15 lines): the project summary, the commands (`uv sync`, ruff, pytest) and the rules (Python 3.12/uv, no secrets or weights or real user data, no connection to the team database, seed data in `data/seed/`, announcements fetched at query time only, Conventional Commits).
- **Why:** unverified. The commit message records no reason.
- **How it was verified:** Docs-only change; nothing to run.
- **Commits:** `5a03dc1`
- **Open questions / next:** `data/seed/` is referenced in `CLAUDE.md` but doesn't exist yet.

## 2026-10-06: Repo setup

- **Date:** 2026-10-06 (14:58–15:06 +08:00)
- **What changed:**
  - `30faba2`: the initial commit, with `README.md` and IDE files under `.idea/`.
  - `79f88d9`: set up the Python project with uv, ruff and pytest (`pyproject.toml`, `uv.lock`, `.python-version` at `3.14`, `src/archways_assistant/__init__.py`). Removed the `.idea/` files from tracking. Git records `.idea/.gitignore` as renamed to the root `.gitignore`, which ignores `.env`, `.venv/`, `__pycache__/`, `.idea/`, `.vscode/`, `models/*.gguf` and `data/generated/`.
- **Why:** unverified. The commit messages record no reason beyond their titles.
- **How it was verified:** unverified. Git history has no record of a test run.
- **Commits:** `30faba2`, `79f88d9`
- **Open questions / next:** `.gitignore` only ignores `models/*.gguf`, so other weight formats may not be covered. It also doesn't cover `.env.*` variants.
