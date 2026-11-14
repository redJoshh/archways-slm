/**
 * Runs tests/vectors/window_vectors.json (excerpt_v2_centred) against the
 * port, without node APIs, so the same check runs under node and Hermes.
 */

import { feedRow, parsePublishedAt } from "./feed.ts";
import { rankScorer } from "./rank.ts";
import { searchRows, type IndexRow, type Matcher } from "./search.ts";
import { centredExcerpt, excerptFor, windowAnchor } from "./window.ts";

export interface WindowVectorFile {
  format: string;
  cases: {
    name: string;
    body: string;
    question: string;
    query: string;
    matcher: Matcher;
    anchor: [number, number] | null;
    expected: string;
  }[];
  search: {
    now: string;
    details: unknown[];
    question: string;
    arguments: unknown;
    matcher: Matcher;
    expected_ids: string[];
    expected_excerpts: string[];
  };
}

export interface WindowVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runWindowVectors(file: WindowVectorFile): WindowVectorReport {
  const failures: string[] = [];
  let total = 0;
  for (const c of file.cases) {
    total++;
    const got = centredExcerpt(c.body, c.question, c.query, c.matcher);
    let ok = got === c.expected;
    if (ok && c.anchor !== null && c.body.toLowerCase().length === c.body.length) {
      ok = JSON.stringify(windowAnchor(c.body, c.question, c.query, c.matcher)) === JSON.stringify(c.anchor);
    }
    if (!ok) failures.push("window " + c.name);
  }
  total++;
  const s = file.search;
  const now = parsePublishedAt(s.now);
  const rows: IndexRow[] = [];
  for (const detail of s.details) {
    const mapped = feedRow(detail);
    if (mapped !== null) rows.push(mapped.row);
  }
  const found = searchRows(
    rows,
    s.arguments,
    now === null ? NaN : now.ms,
    rankScorer("rank_v1", s.question, s.matcher),
    s.matcher,
    excerptFor("excerpt_v2_centred", s.question, s.matcher),
  );
  const ok =
    JSON.stringify(found.map((a) => a.id)) === JSON.stringify(s.expected_ids) &&
    JSON.stringify(found.map((a) => a.excerpt)) === JSON.stringify(s.expected_excerpts);
  if (!ok) failures.push("window search integration");
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
