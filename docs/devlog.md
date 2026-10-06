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

## 2026-10-06: Add how-it-works explainer

- **Date:** 2026-10-06
- **What changed:** Added `docs/how-it-works.md`. It explains the request flow between the student, Spring, Ollama and Postgres, maps each folder, and walks through the contract, `tooldef.py`, `scripts/probe_tool_call.py` and both test files. It ends with what isn't built yet.
- **Why:** The user asked for a written breakdown of how the code in the repo works.
- **How it was verified:** Docs-only change; nothing to run. Its content was checked against the current repo files.
- **Commits:** not committed yet.
- **Open questions / next:** A stray file `s` (saved `git log` output with ANSI color codes) is staged in the index. It looks accidental and should probably be unstaged and deleted.

## 2026-10-06: Generate Ollama tool definition from the contract

- **Date:** 2026-10-06
- **What changed:**
  - Added `src/archways_assistant/tooldef.py`. `build_tool_definition(schema)` builds an Ollama function-tool dict from the schema's `title`, `description` and `$defs/arguments`. Each property keeps only `type` and `description`.
  - Constraint keywords (`minimum`/`maximum`, `minLength`/`maxLength`, `pattern`, `format`, `default`) are turned into description sentences using the schema's values. `$comment` and `additionalProperties` are dropped without a sentence.
  - Any keyword, pattern or format without a rendering rule raises `ValueError`, so a constraint can't be lost silently.
  - Running `uv run python -m archways_assistant.tooldef` writes `generated/search_announcements.tool.json`: 2-space indent, fixed key order, LF line endings and a trailing newline.
  - Added `tests/test_tooldef.py` (9 cases): the committed file is up to date; no dropped keywords or `$ref` appear in it; `required == ["query"]`; the property names match the schema; every property has a description; golden description strings; sentences follow a changed schema value; and `multipleOf` and `$ref` raise `ValueError`.
  - Added a `generated/` rule to `CLAUDE.md`.
- **Why:** To keep the schema as the single source of truth for the tool definition the model sees.
- **How it was verified:**
  - `uv run python -m archways_assistant.tooldef` → `Wrote generated\search_announcements.tool.json`
  - `uv run pytest -v` → `54 passed in 0.30s`
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format .` → `7 files left unchanged`
- **Commits:** `44025cb`, `5729145`, and the commit that adds this entry (`docs: add generated/ rule to CLAUDE.md and devlog entry`)
- **Open questions / next:**
  - The generator finds the schema through `__file__`. This only works with the editable install that `uv sync` sets up, not with a built wheel.
  - The `query` description has two overlapping sentences ("Must not be empty" and the non-whitespace one). They are kept on purpose; nothing is special-cased.
  - Not yet tested against a running Ollama model.

## 2026-10-06: Document year_level semantics

- **Date:** 2026-10-06
- **What changed:** In `contracts/search_announcements.schema.json`, `year_level` now has a model-facing `description`: 1 = first year, 2 = second year, and so on; null = all students. It also has a `$comment`: Spring sends the raw column value, and the future per-student filter is `year_level IS NULL OR year_level = :studentYear`. No `minimum` or `maximum` was added.
- **Why:** The team's Spring repo confirms the semantics: null = all students, a number = that year level. This comes from the user; it wasn't checked from this repo, because the Spring repo is separate.
- **How it was verified:**
  - `uv run pytest` → `45 passed in 0.12s`
  - `uv run ruff check .` → `All checks passed!`
- **Commits:** the commit that adds this entry (`docs: document year_level semantics in contract`)
- **Open questions / next:**
  - The valid range of `year_level` is still unverified, so the schema has no bounds yet.
  - Next step: add an eval case where a result has `year_level: null`, and check that the model says the announcement applies to all students rather than treating the value as missing or unknown.

## 2026-10-06: Document posted_at offset and result ordering

- **Date:** 2026-10-06
- **What changed:**
  - `contracts/search_announcements.schema.json`: added a `$comment` to `posted_at` saying it must include a UTC offset, which Spring attaches because the DB column has no time zone. Added a `$comment` to `$defs/result` saying results are ordered newest first by `posted_at`, Spring guarantees the order, and `maxItems` must equal `arguments.limit.maximum`.
  - `tests/test_search_announcements_schema.py`: added `test_result_max_items_matches_limit_maximum`.
- **Why:** To record the time-zone and ordering guarantees in the contract, and to stop `result.maxItems` and the `limit` maximum from drifting apart.
- **How it was verified:**
  - `uv run pytest -q` → `45 passed in 0.15s`
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `5 files already formatted`
- **Commits:** `0349027`, `16910a1`
- **Open questions / next:** The schema can't check the ordering or that the offset comes from Spring. Both need to be tested on the Spring side.

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
