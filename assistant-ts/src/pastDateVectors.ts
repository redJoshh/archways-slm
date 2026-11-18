/**
 * Runs tests/vectors/past_date_vectors.json (v2 fix (c)) against the port,
 * without node APIs, so the same check runs under node and Hermes. Every case
 * also checks that guard-ts's claims() and guard() read the annotated text
 * exactly as the original.
 */

import { claims, guard } from "../../guard-ts/src/guard.ts";
import { annotatePastDates, pastResultSources } from "./pastDate.ts";
import type { Announcement } from "./render.ts";

export interface PastDateVectorFile {
  format: string;
  rule: "past_date_v1";
  note: string;
  cases: {
    name: string;
    now: string;
    reply: string;
    results: { title: string; excerpt: string }[];
    expected: string;
  }[];
}

export interface PastDateVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

function pastFull(r: { title: string; excerpt: string }, i: number): Announcement {
  return {
    id: String(i + 1),
    title: r.title,
    excerpt: r.excerpt,
    office: "Test Office",
    priority: "NORMAL",
    year_level: null,
    posted_at: "2026-11-06T09:00:00+08:00",
  };
}

function pastSameKeys(a: { [key: string]: true }, b: { [key: string]: true }): boolean {
  const ka = Object.keys(a).sort();
  const kb = Object.keys(b).sort();
  return JSON.stringify(ka) === JSON.stringify(kb);
}

export function runPastDateVectors(file: PastDateVectorFile): PastDateVectorReport {
  const failures: string[] = [];
  let total = 0;
  for (const c of file.cases) {
    total++;
    try {
      const results = c.results.map(pastFull);
      const got = annotatePastDates(c.reply, pastResultSources(results), Date.parse(c.now));
      if (got !== c.expected) {
        failures.push("past_date " + c.name);
        continue;
      }
      const before = claims(c.reply);
      const after = claims(c.expected);
      if (!pastSameKeys(before.dates, after.dates) || !pastSameKeys(before.numbers, after.numbers)) {
        failures.push("past_date claims " + c.name);
        continue;
      }
      const g1 = guard(c.reply, results, "", []);
      const g2 = guard(c.expected, results, "", []);
      if (g1.fired !== g2.fired || JSON.stringify(g1.codes) !== JSON.stringify(g2.codes)) {
        failures.push("past_date guard " + c.name);
      }
    } catch (error) {
      failures.push("past_date threw " + c.name);
    }
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
