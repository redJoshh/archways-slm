/**
 * Runs tests/vectors/strip_nf_vectors.json (fix (g) strip_nf_v1) against the
 * port, without node APIs, so the same check runs under node and Hermes.
 */

import { answerReplyText } from "./flow.ts";

export interface StripNfVectorFile {
  format: string;
  rule: "strip_nf_v1";
  not_found: string;
  cases: { name: string; reply: string; expected: string | null }[];
}

export interface StripNfVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runStripNfVectors(file: StripNfVectorFile): StripNfVectorReport {
  const failures: string[] = [];
  let total = 0;
  for (const c of file.cases) {
    total++;
    if (answerReplyText(c.reply, file.rule) !== c.expected) failures.push("strip_nf " + c.name);
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
