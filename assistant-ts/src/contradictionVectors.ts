/**
 * Runs tests/vectors/contradiction_vectors.json (v2 fix (a)) against the
 * port, without node APIs, so the same check runs under node and Hermes.
 */

import { contradictionFires } from "./contradiction.ts";

export interface ContradictionVectorFile {
  format: string;
  rule: "contradiction_v1";
  cases: {
    name: string;
    question: string;
    reply: string;
    results: { title: string; excerpt: string }[];
    expected: boolean;
  }[];
}

export interface ContradictionVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runContradictionVectors(file: ContradictionVectorFile): ContradictionVectorReport {
  const failures: string[] = [];
  let total = 0;
  for (const c of file.cases) {
    total++;
    let got: boolean | null = null;
    try {
      got = contradictionFires(c.question, c.reply, c.results);
    } catch (error) {
      got = null;
    }
    if (got !== c.expected) failures.push("contradiction " + c.name);
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
