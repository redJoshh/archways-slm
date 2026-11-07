/**
 * Runs tests/vectors/feed_vectors.json against the port, without node APIs,
 * so the same check runs under node and under the Hermes CLI.
 */

import { feedRow, parsePublishedAt } from "./feed.ts";
import { cutCodePoints, plainText } from "./plaintext.ts";
import { searchRows, type IndexRow } from "./search.ts";
import { EXCERPT_CHARS } from "./searchData.ts";

export interface FeedVectorFile {
  format: string;
  matcher: string;
  plain_text: { body: string; expected: string }[];
  cut: { text: string; expected: string }[];
  published_at: { text: unknown; expected: { manila: string; offset_added: boolean } | null }[];
  rows: {
    detail: unknown;
    expected: {
      announcement: { [key: string]: unknown };
      match_title: string;
      match_body: string;
      offset_added: boolean;
    } | null;
  }[];
  search: {
    now: string;
    details: unknown[];
    cases: { name: string; arguments: unknown; ok: boolean; expected_ids: string[] | null }[];
  };
}

export interface FeedVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

function sameObject(a: { [key: string]: unknown }, b: { [key: string]: unknown }): boolean {
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  for (const key of ka) if (!Object.prototype.hasOwnProperty.call(b, key) || a[key] !== b[key]) return false;
  return true;
}

export function runFeedVectors(file: FeedVectorFile, maxFailures = 20): FeedVectorReport {
  const failures: string[] = [];
  let total = 0;
  let failed = 0;
  const record = (label: string, ok: boolean) => {
    total++;
    if (ok) return;
    failed++;
    if (failures.length < maxFailures) failures.push(label);
  };

  for (const v of file.plain_text) record("plain " + JSON.stringify(v.body).slice(0, 60), plainText(v.body) === v.expected);
  for (const v of file.cut) record("cut " + v.text.length, cutCodePoints(v.text, EXCERPT_CHARS) === v.expected);
  for (const v of file.published_at) {
    const got = parsePublishedAt(v.text);
    const ok =
      v.expected === null
        ? got === null
        : got !== null && got.manila === v.expected.manila && got.offsetAdded === v.expected.offset_added;
    record("published_at " + JSON.stringify(v.text), ok);
  }
  for (const v of file.rows) {
    const got = feedRow(v.detail);
    const e = v.expected;
    const ok =
      e === null
        ? got === null
        : got !== null &&
          sameObject(got.row.announcement as unknown as { [key: string]: unknown }, e.announcement) &&
          got.row.title === e.match_title.toLowerCase() &&
          got.row.body === e.match_body.toLowerCase() &&
          got.offsetAdded === e.offset_added;
    record("row " + JSON.stringify(v.detail).slice(0, 60), ok);
  }
  const now = parsePublishedAt(file.search.now);
  const rows: IndexRow[] = [];
  for (const detail of file.search.details) {
    const mapped = feedRow(detail);
    if (mapped !== null) rows.push(mapped.row);
  }
  for (const c of file.search.cases) {
    let ids: string[] | null = null;
    try {
      ids = searchRows(rows, c.arguments, now === null ? NaN : now.ms).map((a) => a.id);
    } catch (error) {
      ids = null;
    }
    const ok = c.ok ? ids !== null && JSON.stringify(ids) === JSON.stringify(c.expected_ids) : ids === null;
    record("search " + c.name, ok);
  }
  return { total: total, passed: total - failed, failed: failed, failures: failures };
}
