/**
 * retry_v1 on the phone: a port of feedindex.search_feed_retry.
 *
 * Rule: docs/plans/accuracy-phase.md, "retry_v1 rule, pre-registered"
 * (2026-11-14), checked by the hand-written tests/vectors/retry_vectors.json.
 *
 * Only after a valid search with 0 results: the question's rank_v1 content
 * words, a row matching if any one is found by the matcher's one-word test
 * (wordFound); the model's days and limit kept; ordered by rank_v1 points,
 * then newest, then id; cut after. No content words: no retry. Invalid
 * arguments throw (searchRows), with no retry.
 */

import { checkArguments } from "./contract.ts";
import type { Announcement } from "./render.ts";
import { questionTerms, rankScorer, rowPoints, wordFound, type RankVersion } from "./rank.ts";
import { searchRows, type IndexRow } from "./search.ts";
import { DAYS_DEFAULT, LIMIT_DEFAULT } from "./searchData.ts";

export type RetryVersion = "retry_v1";

export interface RetryResult {
  results: Announcement[];
  /** true when the retry was attempted, whatever it found. */
  retried: boolean;
}

const RETRY_DAY_MS = 86400000;

export function searchWithRetry(
  rows: IndexRow[],
  args: unknown,
  nowMs: number,
  question: string,
  rank: RankVersion,
  retry: RetryVersion | null,
): RetryResult {
  const first = searchRows(rows, args, nowMs, rankScorer(rank, question));
  if (first.length > 0 || retry === null) return { results: first, retried: false };
  if (retry !== "retry_v1") throw new Error("unknown retry version");
  const terms = questionTerms(question);
  if (terms.words.length === 0) return { results: [], retried: false };
  const checked = checkArguments(args);
  const days = checked.days === undefined ? DAYS_DEFAULT : checked.days;
  const limit = checked.limit === undefined ? LIMIT_DEFAULT : checked.limit;
  const since = nowMs - days * RETRY_DAY_MS;
  const found: { row: IndexRow; points: number }[] = [];
  for (const row of rows) {
    if (row.publishedMs > nowMs || row.publishedMs < since) continue;
    let hit = false;
    for (const word of terms.words) if (!hit && wordFound(word, row.title, row.body)) hit = true;
    if (hit) found.push({ row: row, points: rowPoints(terms, row) });
  }
  found.sort((a, b) => {
    if (a.points !== b.points) return b.points - a.points;
    if (a.row.publishedMs !== b.row.publishedMs) return b.row.publishedMs - a.row.publishedMs;
    const ia = a.row.announcement.id;
    const ib = b.row.announcement.id;
    return ia < ib ? -1 : ia > ib ? 1 : 0;
  });
  return { results: found.slice(0, limit).map((f) => f.row.announcement), retried: true };
}
