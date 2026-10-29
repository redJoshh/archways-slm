# How to write a style anchor

Anchors are 20–30 hand-written announcements that set the style of the synthetic training corpus. A teacher model later expands them to 150–250 rows, and code inserts the traps (long bodies, injected instructions, superseded pairs, year levels). So write plain, ordinary announcements; don't add traps yourself.

**Never copy or paraphrase a real announcement**, from UST or anywhere else. Write every anchor from scratch. Also don't reuse the topics or wording of `data/seed/announcements.json` or of any eval question; `scripts/check_overlap.py` checks this, and flagged anchors are dropped.

## Fields

Each anchor is one JSON object with exactly these fields (the same as the seed rows). Save anchors as a JSON array, e.g. `data/anchors/anchors_v1.json`.

| Field | What to write |
|---|---|
| `id` | `anc-` and three digits: `anc-001`, `anc-002`, … (unique) |
| `title` | A short headline, at most 150 characters, like a notice board title |
| `body` | 2–5 sentences, about 150–450 characters. Give the key facts (what, who, when, where, how) with exact dates and times, e.g. `November 18, 2026 from 2:00 PM to 5:00 PM` |
| `office` | The office posting it, e.g. "Office of Student Affairs" style names |
| `priority` | `"NORMAL"` or `"HIGH"` |
| `year_level` | `null` (all students) or a year number like `2`; mostly `null` |
| `published_at` | When it was posted, `YYYY-MM-DDTHH:MM:SS`, no time zone, e.g. `2026-11-03T09:00:00` |
| `status` | `"PUBLISHED"` (use `"DRAFT"` for only one or two anchors) |
| `is_archived` | `false` (use `true` for only one or two anchors) |
| `scheduled` | `false` |

## Tone

- Formal and polite, like an official university office. No slang, no emoji.
- English only. (Questions about the anchors may later be in Filipino or Taglish, but announcements stay in English.)
- One matter per announcement. Vary the offices, the kinds of events (deadlines, closures, schedules, sign-ups, services) and the dates.
- Every fact must be inside the announcement itself: no "see the attached file" and no links.

## Check before handing them over

```powershell
uv run pytest -q tests/test_synthetic.py
uv run python scripts/check_overlap.py data/seed/announcements.json data/anchors/anchors_v1.json --protected-field title --candidate-field title --show-candidates
uv run python scripts/check_overlap.py data/seed/announcements.json data/anchors/anchors_v1.json --protected-field body --candidate-field body --show-candidates
```

The tests validate every JSON file in `data/anchors/`. Rewrite any anchor the overlap check flags.

## Example

`data/anchors/example_anchor.json` is a deliberately fictional example: a moon campus and an origami guild that don't exist. Copy its shape, not its content. It is not a training anchor; only the anchor files you write (e.g. `anchors_v1.json`) feed the corpus.
