/**
 * window_v1 on the phone: a port of feedindex.search_feed_window.
 *
 * Rule: docs/plans/window-fallback.md, section 3 (approved 2026-11-17),
 * checked by the hand-written tests/vectors/window_fallback_vectors.json.
 *
 * Only after a valid search with 0 results, and only if days is DAYS_MAX
 * (30; the default 7 or any shorter period the student named stays a hard
 * filter): the same search again over nowMs - 365 days <= published <= nowMs,
 * with the same query, matcher, rank, limit and excerpt rule. fellBack is
 * true whenever that second search ran, whatever it found. Invalid
 * arguments throw (searchRows), with no fallback.
 */

import { checkArguments } from "./contract.ts";
import { DAYS_MAX } from "./generated.ts";
import type { Announcement } from "./render.ts";
import { DAYS_DEFAULT } from "./searchData.ts";

export type FallbackVersion = "window_v1";

export const FALLBACK_DAYS = 365;

export interface FallbackResult {
  results: Announcement[];
  /** true when the 365-day search ran, whatever it found. */
  fellBack: boolean;
}

/**
 * search(windowDays): the caller's search, with windowDays undefined for the
 * model's own days, or FALLBACK_DAYS for the fallback.
 */
export function searchWithFallback(
  search: (windowDays?: number) => Announcement[],
  args: unknown,
  fallback: FallbackVersion | null,
): FallbackResult {
  if (fallback !== null && fallback !== "window_v1") throw new Error("unknown fallback version");
  const first = search(undefined);
  if (first.length > 0 || fallback === null) return { results: first, fellBack: false };
  const checked = checkArguments(args);
  const days = checked.days === undefined ? DAYS_DEFAULT : checked.days;
  if (days !== DAYS_MAX) return { results: first, fellBack: false };
  return { results: search(FALLBACK_DAYS), fellBack: true };
}
