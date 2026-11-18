/**
 * Runs the hand-written tests/vectors/and_v5_vectors.json against the port
 * (and_v5 and and_v4, rank_v1 on), without node APIs, so the same check runs
 * under node and the Hermes CLI. v2 fix (e), the Taglish lexicon v1.
 */

import { feedRow, parsePublishedAt } from "./feed.ts";
import { questionTerms, rankScorer, rowPoints } from "./rank.ts";
import { searchRows, synonymsFor, type IndexRow, type Matcher } from "./search.ts";

interface AndV5Expectation {
  expected_ids: string[];
  expected_points: number[];
}

export interface AndV5VectorFile {
  format: string;
  matcher: string;
  now: string;
  details: unknown[];
  cases: {
    name: string;
    question: string;
    arguments: unknown;
    and_v5: AndV5Expectation;
    and_v4: AndV5Expectation;
  }[];
}

export interface AndV5VectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runAndV5Vectors(file: AndV5VectorFile): AndV5VectorReport {
  const failures: string[] = [];
  let total = 0;
  const parsedNow = parsePublishedAt(file.now);
  const atMs = parsedNow === null ? NaN : parsedNow.ms;
  const v5Rows: IndexRow[] = [];
  const v5ById: { [id: string]: IndexRow } = {};
  for (const detail of file.details) {
    const mapped = feedRow(detail);
    if (mapped === null) continue;
    v5Rows.push(mapped.row);
    v5ById[mapped.row.announcement.id] = mapped.row;
  }
  const v5Matchers: Matcher[] = ["and_v5", "and_v4"];
  for (const c of file.cases) {
    const terms = questionTerms(c.question);
    for (const matcher of v5Matchers) {
      total++;
      const expected = matcher === "and_v5" ? c.and_v5 : c.and_v4;
      let ids: string[] | null = null;
      try {
        ids = searchRows(v5Rows, c.arguments, atMs, rankScorer("rank_v1", c.question, matcher), matcher).map(
          (a) => a.id,
        );
      } catch (error) {
        ids = null;
      }
      const points = ids === null ? null : ids.map((id) => rowPoints(terms, v5ById[id], synonymsFor(matcher)));
      const ok =
        JSON.stringify(ids) === JSON.stringify(expected.expected_ids) &&
        JSON.stringify(points) === JSON.stringify(expected.expected_points);
      if (!ok) failures.push(matcher + " " + c.name);
    }
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
