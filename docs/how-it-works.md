# How archways-assistant works

This repo is the **Python side** of a local AI assistant for UST Archways. It does not answer questions or search a database itself. Its job is to define, test and probe **one tool**, `search_announcements`, that a small language model (running locally in Ollama) can call. The Java/Spring app (separate repo) is what actually runs the search against Postgres.

## The big picture

```mermaid
sequenceDiagram
    participant U as Student
    participant S as Spring app (other repo)
    participant O as Ollama (local model)
    participant DB as Postgres

    U->>S: "Any announcements from the registrar?"
    S->>O: question + tool definition (generated/search_announcements.tool.json)
    O-->>S: tool call: search_announcements {"query": "registrar"}
    S->>S: validate args, apply defaults (days=7, limit=5)
    S->>DB: query PUBLISHED, non-archived announcements only
    DB-->>S: rows
    S->>O: results (shaped like $defs/result)
    O-->>S: natural-language answer
    S-->>U: answer
```

The model never touches the database and never "knows" announcements from training. It only asks for them through the tool, at question time.

## Folder map

| Path | What it is |
|---|---|
| `contracts/search_announcements.schema.json` | **The source of truth.** A JSON Schema describing the tool's arguments and its results. |
| `contracts/search_synonyms_v1.json` | Frozen synonym map for search contract v2 (the and_v2 matcher). Spring loads the same file. |
| `tests/vectors/search_vectors_and_v2.json` | Search vectors that Spring's and_v2 implementation must pass. |
| `src/archways_assistant/tooldef.py` | Generator that turns the contract into the tool definition Ollama understands. |
| `generated/search_announcements.tool.json` | Output of the generator. Never edit by hand. |
| `scripts/probe_tool_call.py` | Sends test questions to a local Ollama model and checks whether it calls the tool correctly. |
| `src/archways_assistant/toolparse.py` | Parses a model's plain-text reply into a tool call, no tool, or malformed (used by the probe's prompt mode). |
| `prompts/system_v1.txt` | The system prompt the probe sends, with a `{today}` placeholder. New versions are new files. |
| `prompts/system_v1_prompt_mode.txt` | `system_v1.txt` plus a `{tool_definition}` placeholder and JSON reply instructions, for models without tool support. |
| `evals/dev_questions.jsonl` | The 30 development questions the probe asks by default, one JSON object per line. |
| `tests/test_search_announcements_schema.py` | Tests that the contract accepts good data and rejects bad data. |
| `tests/test_tooldef.py` | Tests that the generated file is up to date and correct. |
| `tests/test_toolparse.py` | Tests the reply parser on every reply shape (no Ollama needed). |
| `tests/test_prompts.py` | Tests that the prompt-mode prompt starts with the exact text of `system_v1.txt`. |
| `src/archways_assistant/__init__.py` | Placeholder `main()` from `uv init`; prints a hello message. Not used yet. |
| `docs/devlog.md` | Dated development history, newest first. |
| `CLAUDE.md` | Project rules (no secrets, no real DB, defaults live in Spring, etc.). |
| `pyproject.toml`, `uv.lock`, `.python-version` | Python 3.12 project managed by uv. Runtime has no dependencies; dev tools are `pytest`, `ruff`, `jsonschema`, `rfc3339-validator`, `httpx`. |

## 1. The contract (`contracts/search_announcements.schema.json`)

A JSON Schema (draft 2020-12) with ID `urn:archways:tool:search-announcements:v1`. The `v1` matters: a breaking change gets a new `v2` instead of editing v1, so both apps can tell which version they speak.

It has three parts under `$defs`:

### `arguments`: what the model sends

| Field | Type | Rules | Default |
|---|---|---|---|
| `query` | string | **required**, 1–200 chars, must contain a non-space character | — |
| `days` | integer | 1–30, how far back to look by publish date | 7 |
| `limit` | integer | 1–10, max results | 5 |

`additionalProperties: false` means the model can't invent extra fields. The defaults are only **documented** here; the Spring app is responsible for applying them.

### `announcement`: one search result

`id`, `title` (≤255), `excerpt` (≤500, Spring truncates the body), `office`, `priority`, `year_level` and `posted_at`. All are required.

- `year_level`: an integer (1 = first year, …) or `null`, which means *all students*.
- `posted_at`: a date-time that **must include a UTC offset** like `+08:00`. The DB column has no time zone, so Spring attaches one.

### `result`: what Spring sends back

An array of announcements, newest first, at most 10 items. That 10 must match `arguments.limit.maximum`.

### Two kinds of text in the schema

- `description` is **written for the model**. It ends up in the prompt.
- `$comment` holds **notes for developers** (Spring's responsibilities, design rules). It is never sent to the model.

### Search contract version 2 (matching)

The search contract is now **version 2** (2026-10-31). The arguments and results are the same as above. Only the matching changes: Spring must search with **and_v2**.

- **and_v2:** the query is lowercased and split on whitespace, and the and_v1 stopwords plus the map's `extra_stopwords` ("kapag") are dropped. Each remaining word, with its synonyms from [`contracts/search_synonyms_v1.json`](../contracts/search_synonyms_v1.json), forms a group: `(title ILIKE '%alt%' OR body ILIKE '%alt%' …)` over the word and its synonyms, escaped as `ilike_pattern()` does (escape char `\`). Every group must match (AND across words). Visibility, the days window, newest-first order and limit are unchanged.
- **The map file is frozen.** A hash test pins it. A change is a new file (`search_synonyms_v2.json`) and a new matcher, never an edit. Spring must load this same file, not a copy.
- **Vectors:** Spring's search must pass [`tests/vectors/search_vectors_and_v2.json`](../tests/vectors/search_vectors_and_v2.json) (and_v2) as well as [`tests/vectors/search_vectors.json`](../tests/vectors/search_vectors.json) (visibility, window, limit, validation and escaping, shared with and_v1).
- **No new schema file:** the schema's `$id` stays `...:v1`, because the arguments and results did not change. "Version 2" names the matching behaviour. `src/archways_assistant/fakebackend.py` is the reference implementation (`DEFAULT_MATCHER = "and_v2"`).
- **Caveats:** the map was built from dev-set retrieval failures, so it is not evidence of held-out quality. It is untested on real announcements; for example, "due" also matches "due to".

## 2. The generator (`src/archways_assistant/tooldef.py`)

Ollama expects tools in a simpler "function tool" format, and small models do better with plain-English hints than with JSON Schema keywords. The generator bridges the two.

Run it with:

```bash
uv run python -m archways_assistant.tooldef
```

Step by step:

1. `main()` reads the contract and calls `build_tool_definition(schema)`.
2. `build_tool_definition` takes the schema's `title` as the function name, its `description` as the function description, and `$defs/arguments` as the parameters.
3. For each argument, `build_property` keeps only `type` and `description`.
4. `describe_constraints` turns the constraint keywords into sentences appended to the description:
   - `minimum` + `maximum` → "Whole number from 1 to 30."
   - `minLength: 1` → "Must not be empty."
   - `maxLength` → "At most 200 characters."
   - `pattern: "\S"` → "Must contain at least one non-whitespace character." (looked up in `PATTERNS`)
   - `format` → a sentence from `FORMATS`
   - `default` → "Default 7."
5. `$comment` and `additionalProperties` are dropped silently (`SILENT_KEYWORDS`).
6. **Safety net:** `check_keywords` raises `ValueError` if the schema contains any keyword, pattern or format the generator has no rule for (e.g. `multipleOf`, `$ref`). That way a constraint can never be silently lost from the model's view.
7. `render` writes the JSON with 2-space indent, LF line endings and a trailing newline, so the output is byte-for-byte stable.

Result, for example the `days` property:

```json
"days": {
  "type": "integer",
  "description": "How many days back to look, by publication date. Whole number from 1 to 30. Default 7."
}
```

Paths are found relative to `__file__`, so this works with the editable install `uv sync` sets up but not from a built wheel.

## 3. The probe script (`scripts/probe_tool_call.py`)

An experiment harness: *does a small local model actually use the tool well?* The prompt and the questions live in files, so two runs can be compared just by their inputs.

```bash
uv run python scripts/probe_tool_call.py --model qwen3:1.7b --tool-mode native \
    --prompt prompts/system_v1.txt --questions evals/dev_questions.jsonl
```

All four flags are optional; the values above are the defaults. Paths you pass are relative to the current directory. With `--tool-mode prompt`, the default prompt is `prompts/system_v1_prompt_mode.txt` (see [Tool modes](#tool-modes)).

To run only some questions, add `--ids` with comma-separated IDs. They run in file order, and an unknown ID stops the run with its name:

```bash
uv run python scripts/probe_tool_call.py --ids dev-001,dev-004,dev-011
```

To save a run (PowerShell), write it to `runs/`. That folder is gitignored, so saving output doesn't make the tree `-dirty`, and run outputs are never committed:

```powershell
New-Item -ItemType Directory runs -Force
uv run python scripts/probe_tool_call.py --model qwen3:1.7b | Tee-Object runs/<name>.txt
```

What it does:

1. Loads the generated tool and the contract's `arguments` schema (for validation).
2. Reads the system prompt from `--prompt` and replaces `{today}` with today's date in Manila time, e.g. `Thursday, 2026-10-08` (fixed `+08:00`; the Philippines has no DST). The file must contain `{today}`. `system_v1.txt` tells the model to call the tool with short keywords, not full sentences, and never to invent announcements.
3. Reads the questions from `--questions` (format below) and stops with the file and line number if a line is invalid or an `id` repeats.
4. Prints one header line that pins down the run:
   ```
   model=qwen3:1.7b tool_mode=native capabilities=completion,tools,thinking prompt=prompts/system_v1.txt questions=evals/dev_questions.jsonl ollama=0.40.4 commit=a0ea9c3 today=2026-10-15
   ```
   `capabilities` comes from Ollama's `/api/show` (`unknown` if Ollama doesn't report them). With `--ids`, an `ids=...` field follows `questions=`; full runs don't have it. Since commit `ffcd245` the sampling options follow, as `temperature=0 top_k=1 top_p=1 seed=42` (older headers show only `seed=42`, or nothing). `commit` is the short git hash, with `-dirty` added if the work tree has any uncommitted or untracked changes, because then the hash doesn't fully describe the code or prompt that ran.
5. Sends each question to `http://localhost:11434/api/chat`, one at a time, with the sampling options `SAMPLING_OPTIONS` (`temperature: 0`, `top_k: 1`, `top_p: 1`, `seed: 42`; greedy decoding, shared with the [end-to-end probe](#the-end-to-end-probe-scriptsprobe_end_to_endpy)). It sends no `num_ctx`, so Ollama's default applies. It adds `think: false` only if the model's capabilities include `thinking` (or are unknown), because models without thinking, like `gemma3`, reject it. Each answer's block starts with its position and question ID, e.g. `[3/30] dev-004: When is the enrollment deadline?`. Outputs from before commit `4ce37b4` have no ID there. For each answer it reports:
   - whether the tool was called, and whether that was the right decision,
   - whether the arguments pass the contract (`jsonschema` validator),
   - whether `query` looks like a sentence (more than 6 words or ends with `?`) instead of keywords,
   - latency, prompt tokens and tokens/second from Ollama's timing fields.
6. Prints a summary: correct decisions, valid arguments and sentence-like queries, then correct decisions per category with the ids of the wrong ones. With `--ids`, it counts only the selected questions.

Every earlier run also sent `temperature: 0`; only `top_k` and `top_p` were at the model's defaults before `ffcd245`. Even with greedy options, two runs of the same inputs can differ (reply wording, argument key order) while the model stays loaded: in the end-to-end diagnostic, a warm model's reply depended on the previous call. With the model unloaded after every call, the replies were identical. See the [devlog, 2026-10-29](devlog.md#2026-10-29-explicit-greedy-decoding-and-a-cache-state-diagnostic). Unless you measure that way, compare the decision and validity counts, not exact text.

### Tool modes

- **`native`** (default): the tool goes in Ollama's `tools` field and calls come back in `message.tool_calls`. Models without tool support (e.g. `gemma3:1b`) fail with HTTP 400 "does not support tools".
- **`prompt`**: no `tools` field. The prompt's `{tool_definition}` placeholder is filled with `generated/search_announcements.tool.json`, and the model is told to reply with only `{"name": "search_announcements", "arguments": {...}}` to search. `toolparse.parse_reply` classifies the reply text:
  - **tool call**: exactly one `{"name": string, "arguments": object}`, even in a code fence or with prose around it. A wrong name still counts as a call, and the usual name check marks it invalid, the same as in native mode.
  - **malformed**: a plausible attempt that can't be parsed into that shape (the reply starts with `{` after any code fence, or names `search_announcements` next to a brace). It always scores as a WRONG decision, prints a `parse error:` line, and is counted in a `malformed: N/30` summary line.
  - **no tool**: anything else, including prose that happens to contain braces.

A prompt with a `{tool_definition}` placeholder only runs in prompt mode, and one without it only runs in native mode, so a run can't silently use the wrong prompt. The `malformed` and `parse error` lines only appear in prompt mode.

### Question files

One JSON object per line; blank lines are skipped and extra keys are ignored:

```json
{"id": "dev-001", "question": "May pasok ba bukas?", "expects_tool": true, "category": "class_suspension"}
```

`evals/dev_questions.jsonl` has 30 questions in 11 categories: 18 should trigger the tool (class suspensions, deadlines, offices, year levels, relative dates, typos and slang) and 12 should not (small talk, math and poems, prompt injection, vague messages with no context, and requests for data the model must never see, like drafts or admin notes). Use this file while iterating on prompts.

A **held-out** file, written by hand from real student questions, will be used only for final comparisons. Any file in the same format works with `--questions`. Eval questions must never be copied into a system prompt or training data, or the scores stop meaning anything.

### Prompt versions

Prompts are versioned by file name. To try a change, copy `system_v1.txt` to `system_v2.txt` and edit the copy; never edit an old version. Then every old header line still points at the prompt that actually ran.

It only talks to localhost (`trust_env=False` ignores proxy env vars), never reads `.env` and never touches a database. It doesn't execute the tool; it only inspects what the model *asks for*.

### The end-to-end probe (`scripts/probe_end_to_end.py`)

Question → search → final reply, scored on the final reply; its docstring describes each step. Both of its Ollama calls (the query call and the answer call) send the same `SAMPLING_OPTIONS` as above, plus `num_ctx: 4096`. The header prints them next to `num_ctx`, `num_gpu` and the Ollama version.

- `--ids e2e-009,e2e-032` runs only those cases.
- `--repeat N` runs the selected cases N times in one process (all cases, then all again). The header adds `repeat=N`, and the summary counts every repeat as a case.
- `--keep-alive 0` sends Ollama's top-level `keep_alive` field on every chat call, so the model unloads after each call and every call starts cold. A bare number is sent as seconds, anything else (e.g. `5m`) as a duration string. The header adds `keep_alive=...`. Without the flag the field is not sent.
- `--num-gpu 0` sends `num_gpu: 0` (CPU only); `--matcher` picks the fake backend's matcher.

The reproducible (cold) measurement, with one `ollama serve` started with `OLLAMA_NUM_PARALLEL=1`:

```powershell
$env:OLLAMA_NUM_PARALLEL = "1"; ollama serve   # in its own window
uv run python scripts/probe_end_to_end.py --model gemma3:1b --num-gpu 0 --keep-alive 0 | Tee-Object runs/<name>.txt
```

Why these settings: [devlog, 2026-10-29](devlog.md#2026-10-29-explicit-greedy-decoding-and-a-cache-state-diagnostic).

## 4. The tests

Run them with `uv run pytest`.

**`test_search_announcements_schema.py`** treats the contract like code:
- The schema itself is valid draft 2020-12, and its `$id` ends in `:v1`.
- Good arguments and results pass; bad ones fail (empty or whitespace-only query, out-of-range `days`/`limit`, extra fields, missing fields, `posted_at` without an offset, more than 10 results, …).
- It uses a `referencing.Registry` so it can validate against `$defs/...` by `$ref`.

**`test_tooldef.py`** guards the generator:
- `test_generated_file_is_up_to_date`: the committed `generated/` file equals a fresh render. If you change the contract and forget to rerun the generator, this fails.
- No dropped keywords or `$ref` leak into the output, `required == ["query"]`, property names and order match the schema, and every property has a description.
- Golden strings pin the exact descriptions the model sees.
- Changing a schema value changes the sentence, and unknown keywords such as `multipleOf` or `$ref` raise `ValueError`.

## How a change flows through the repo

1. Edit `contracts/search_announcements.schema.json`.
2. Run `uv run python -m archways_assistant.tooldef` to regenerate `generated/`.
3. Run `uv run pytest` (schema tests plus the up-to-date check).
4. Optionally run the probe against Ollama to see how the model reacts. Commit first so the header shows a clean hash.
5. Mirror the change in the Spring app (defaults, allowlist, result shape).

## Key rules behind the design (from `CLAUDE.md`)

- **One source of truth:** the contract. The tool definition is generated from it.
- **Security lives in Spring, not the prompt:** only PUBLISHED, non-archived announcements may reach the model, enforced with an allowlist in the SQL query. A prompt can be talked around; a `WHERE` clause can't.
- **Defaults live in Spring:** the schema only documents them.
- **No real data:** never connect to the team DB; use seed data in `data/seed/` (not created yet).
- **No training on announcements:** they're fetched live, so the model can't repeat stale or made-up news.
- **Clean evals:** eval questions never go into prompts or training data, and the held-out file is only for final comparisons.
- **Immutable prompt versions:** a prompt change is a new file in `prompts/`.

## Not built yet

- `data/seed/` and any seed data.
- The held-out question file (to be written by hand from real student questions).
- An actual app entry point (`main()` is still the `uv init` placeholder).
- Eval cases checking how the model *describes* results, e.g. that `year_level: null` means "all students".
- `priority` is a free string; it could become an `enum` once the allowed values are known.
