/**
 * Runs the hand-written tests/vectors/retry_vectors.json against the port,
 * without node APIs, so the same check runs under node and the Hermes CLI.
 */

import { feedRow, parsePublishedAt } from "./feed.ts";
import { searchWithRetry } from "./retry.ts";
import type { IndexRow } from "./search.ts";

export interface RetryVectorFile {
  format: string;
  retry: string;
  now: string;
  details: unknown[];
  cases: {
    name: string;
    question: string;
    arguments: unknown;
    ok: boolean;
    expected_ids: string[] | null;
    retried: boolean;
  }[];
}

export interface RetryVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runRetryVectors(file: RetryVectorFile): RetryVectorReport {
  const failures: string[] = [];
  let total = 0;
  const now = parsePublishedAt(file.now);
  const nowMs = now === null ? NaN : now.ms;
  const rows: IndexRow[] = [];
  for (const detail of file.details) {
    const mapped = feedRow(detail);
    if (mapped !== null) rows.push(mapped.row);
  }
  for (const c of file.cases) {
    total++;
    let ids: string[] | null = null;
    let retried = false;
    try {
      const found = searchWithRetry(rows, c.arguments, nowMs, c.question, "rank_v1", "retry_v1");
      ids = found.results.map((a) => a.id);
      retried = found.retried;
    } catch (error) {
      ids = null;
    }
    const ok = c.ok
      ? ids !== null && JSON.stringify(ids) === JSON.stringify(c.expected_ids) && retried === c.retried
      : ids === null;
    if (!ok) failures.push("retry " + c.name);
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
