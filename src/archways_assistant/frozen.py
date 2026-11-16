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
