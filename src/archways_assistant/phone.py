"""Phone-only product settings, kept OUTSIDE the frozen FINAL configuration.

The shipped app = frozen.FINAL (the evaluated configuration, never edited
after the held-out final) + the settings here. scripts/export_assistant_ts.py
writes them into assistant-ts/src/generated.ts as PHONE_* defaults.

- FALLBACK "window_v1" (docs/plans/window-fallback.md; user, 2026-11-17):
  makeFeedSearch() searches again over 365 days after 0 results at days 30.
  It provably can't change any dev or held-out result at the evaluation
  dates (tests/test_window_fallback.py); it changes behaviour from about
  2026-12-07, when the snapshot leaves the 30-day window (its purpose).

No Python evaluation path reads this module: eval_heldout.py --config final
and the dev runs stay exactly as evaluated.
"""

FALLBACK = "window_v1"
