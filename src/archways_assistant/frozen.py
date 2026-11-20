"""The accuracy phase's frozen FINAL configuration (accuracy-phase.md, section 3).

The one source for both consumers:

- scripts/export_assistant_ts.py writes it into assistant-ts/src/generated.ts
  as the phone defaults (PHONE_*): makeFeedSearch() and askAssistant().
- scripts/eval_heldout.py --config final runs it on the held-out set.

Kept (2026-11-14 to 2026-11-16): rank_v1, and_v4, strip_nf_v1, answer prompt
v1. Off: retry_v1 (dropped), gate_v1 (dropped), excerpt_v2_centred (off by the
user's decision), answer prompt v4 (dropped). Never edit after the held-out
final run; a later change is a v2 on a new held-out set (ADR 0007).

The Python flow()/search_feed() defaults stay the baseline configuration:
--verify-baseline and eval_heldout.py --config baseline depend on them.

v2 (docs/plans/v2-improvements.md; frozen 2026-11-20, user approval):
FINAL_V2 is the v2 kept set, and from its freeze the phone defaults
(PHONE_*) come from FINAL_V2. FINAL itself is unchanged: it is the v1
held-out record and the base of eval_heldout.py --config shipped (the v2
baseline). eval_heldout.py --config final_v2 runs FINAL_V2 + window_v1
(archways_assistant.phone) on the v2 held-out file. Never edit FINAL_V2
after the v2 final run; a later change is a v3 on a new held-out set.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    rank: str | None
    matcher: str
    retry: str | None
    excerpt: str | None
    strip_nf: str | None
    answer_prompt: str


FINAL = Config(
    rank="rank_v1",
    matcher="and_v4",
    retry=None,
    excerpt=None,
    strip_nf="strip_nf_v1",
    answer_prompt="prompts/e2e_answer_v1.txt",
)


@dataclass(frozen=True)
class ConfigV2:
    """FINAL's fields plus the v2 post-processing rules (each None = off)."""

    rank: str | None
    matcher: str
    retry: str | None
    excerpt: str | None
    strip_nf: str | None
    answer_prompt: str
    contradiction: str | None
    echo: str | None
    past_date: str | None
    extract: str | None


# Kept (2026-11-18 to 2026-11-19): (e) and_v5 (the Taglish lexicon v1),
# (a) contradiction_v1, (b) echo_v1, (c) past_date_v1, (d) extract_v1, on top
# of FINAL. Dropped: (f) answer prompt v5 (its code stays off).
FINAL_V2 = ConfigV2(
    rank="rank_v1",
    matcher="and_v5",
    retry=None,
    excerpt=None,
    strip_nf="strip_nf_v1",
    answer_prompt="prompts/e2e_answer_v1.txt",
    contradiction="contradiction_v1",
    echo="echo_v1",
    past_date="past_date_v1",
    extract="extract_v1",
)
