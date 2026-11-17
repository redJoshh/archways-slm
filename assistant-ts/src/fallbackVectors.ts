/**
 * Runs the hand-written tests/vectors/window_fallback_vectors.json against
 * the port, without node APIs, so the same check runs under node and the
 * Hermes CLI. Every case searches as the phone does (FINAL: rank_v1, and_v4,
 * the first-500 excerpt).
 */

import { feedRow, parsePublishedAt } from "./feed.ts";
import { searchWithFallback } from "./fallback.ts";
import { rankScorer } from "./rank.ts";
import { searchRows, type IndexRow } from "./search.ts";

export interface FallbackVectorFile {
  format: string;
  window: string;
  rank: string;
  matcher: string;
  now: string;
  fallback_days: number;
  details: unknown[];
  cases: {
    name: string;
    question: string;
    arguments: unknown;
    ok: boolean;
    expected_ids: string[] | null;
    fell_back: boolean;
  }[];
}

export interface FallbackVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runFallbackVectors(file: FallbackVectorFile): FallbackVectorReport {
  const failures: string[] = [];
  let total = 0;
  const parsedNow = parsePublishedAt(file.now);
  const atMs = parsedNow === null ? NaN : parsedNow.ms;
  const indexRows: IndexRow[] = [];
  for (const detail of file.details) {
    const mapped = feedRow(detail);
    if (mapped !== null) indexRows.push(mapped.row);
  }
  for (const c of file.cases) {
    total++;
    let ids: string[] | null = null;
    let fellBack = false;
    try {
      const scorer = rankScorer("rank_v1", c.question, "and_v4");
      const found = searchWithFallback(
        (windowDays) => searchRows(indexRows, c.arguments, atMs, scorer, "and_v4", undefined, windowDays),
        c.arguments,
        "window_v1",
      );
      ids = found.results.map((a) => a.id);
      fellBack = found.fellBack;
    } catch (error) {
      ids = null;
    }
    const ok = c.ok
      ? ids !== null && JSON.stringify(ids) === JSON.stringify(c.expected_ids) && fellBack === c.fell_back
      : ids === null;
    if (!ok) failures.push("fallback " + c.name);
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
