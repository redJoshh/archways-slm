/**
 * Runs the hand-written tests/vectors/and_v4_vectors.json against the port
 * (and_v4 and and_v3, rank_v1 on), without node APIs, so the same check runs
 * under node and the Hermes CLI.
 */

import { feedRow, parsePublishedAt } from "./feed.ts";
import { questionTerms, rankScorer, rowPoints } from "./rank.ts";
import { searchRows, synonymsFor, type IndexRow, type Matcher } from "./search.ts";

interface MatcherExpectation {
  expected_ids: string[];
  expected_points: number[];
}

export interface AndV4VectorFile {
  format: string;
  matcher: string;
  now: string;
  details: unknown[];
  cases: {
    name: string;
    question: string;
    arguments: unknown;
    and_v4: MatcherExpectation;
    and_v3: MatcherExpectation;
  }[];
}

export interface AndV4VectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runAndV4Vectors(file: AndV4VectorFile): AndV4VectorReport {
  const failures: string[] = [];
  let total = 0;
  const now = parsePublishedAt(file.now);
  const nowMs = now === null ? NaN : now.ms;
  const rows: IndexRow[] = [];
  const byId: { [id: string]: IndexRow } = {};
  for (const detail of file.details) {
    const mapped = feedRow(detail);
    if (mapped === null) continue;
    rows.push(mapped.row);
    byId[mapped.row.announcement.id] = mapped.row;
  }
  const matchers: Matcher[] = ["and_v4", "and_v3"];
  for (const c of file.cases) {
    const terms = questionTerms(c.question);
    for (const matcher of matchers) {
      total++;
      const expected = matcher === "and_v4" ? c.and_v4 : c.and_v3;
      let ids: string[] | null = null;
      try {
        ids = searchRows(rows, c.arguments, nowMs, rankScorer("rank_v1", c.question, matcher), matcher).map(
          (a) => a.id,
        );
      } catch (error) {
        ids = null;
      }
      const points =
        ids === null ? null : ids.map((id) => rowPoints(terms, byId[id], synonymsFor(matcher)));
      const ok =
        JSON.stringify(ids) === JSON.stringify(expected.expected_ids) &&
        JSON.stringify(points) === JSON.stringify(expected.expected_points);
      if (!ok) failures.push(matcher + " " + c.name);
    }
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
