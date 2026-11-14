/**
 * Runs the hand-written tests/vectors/rank_vectors.json against the port,
 * without node APIs, so the same check runs under node and the Hermes CLI.
 */

import { feedRow, parsePublishedAt } from "./feed.ts";
import { questionTerms, rankScorer, rowPoints } from "./rank.ts";
import { searchRows, type IndexRow } from "./search.ts";

export interface RankVectorFile {
  format: string;
  rank: string;
  now: string;
  details: unknown[];
  cases: {
    name: string;
    question: string;
    arguments: unknown;
    expected_terms: { words: string[]; dates: string[]; numbers: string[] };
    possible: number;
    expected_ids: string[];
    expected_points: number[];
    unranked_ids: string[];
  }[];
}

export interface RankVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

function sameJson(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function runRankVectors(file: RankVectorFile): RankVectorReport {
  const failures: string[] = [];
  let total = 0;
  const record = (label: string, ok: boolean) => {
    total++;
    if (!ok) failures.push(label);
  };
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
  for (const c of file.cases) {
    const terms = questionTerms(c.question);
    const e = c.expected_terms;
    record(
      "terms " + c.name,
      sameJson(terms.words, e.words) && sameJson(terms.dates, e.dates) && sameJson(terms.numbers, e.numbers),
    );
    record("possible " + c.name, terms.possible === c.possible);
    let ranked: string[] | null = null;
    let unranked: string[] | null = null;
    try {
      ranked = searchRows(rows, c.arguments, nowMs, rankScorer("rank_v1", c.question)).map((a) => a.id);
      unranked = searchRows(rows, c.arguments, nowMs).map((a) => a.id);
    } catch (error) {
      ranked = null;
    }
    record("ranked " + c.name, sameJson(ranked, c.expected_ids));
    record("unranked " + c.name, sameJson(unranked, c.unranked_ids));
    const points = c.expected_ids.map((id) => (byId[id] === undefined ? -1 : rowPoints(terms, byId[id])));
    record("points " + c.name, sameJson(points, c.expected_points));
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
