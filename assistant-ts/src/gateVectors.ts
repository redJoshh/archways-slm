/**
 * Runs the hand-written tests/vectors/gate_vectors.json against the port,
 * without node APIs, so the same check runs under node and the Hermes CLI.
 */

import { feedRow } from "./feed.ts";
import { gateV1, questionTerms, rowPoints } from "./rank.ts";
import { synonymsFor, type IndexRow, type Matcher } from "./search.ts";

export interface GateVectorFile {
  format: string;
  details: unknown[];
  cases: {
    name: string;
    question: string;
    top_id: string;
    matcher: Matcher;
    theta: [number, number];
    points: number;
    possible: number;
    passes: boolean;
  }[];
}

export interface GateVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runGateVectors(file: GateVectorFile): GateVectorReport {
  const failures: string[] = [];
  const byId: { [id: string]: IndexRow } = {};
  for (const detail of file.details) {
    const mapped = feedRow(detail);
    if (mapped !== null) byId[mapped.row.announcement.id] = mapped.row;
  }
  for (const c of file.cases) {
    const row = byId[c.top_id];
    const terms = questionTerms(c.question);
    const ok =
      row !== undefined &&
      rowPoints(terms, row, synonymsFor(c.matcher)) === c.points &&
      terms.possible === c.possible &&
      gateV1(c.question, row, c.matcher, c.theta[0], c.theta[1]) === c.passes;
    if (!ok) failures.push("gate " + c.name);
  }
  return { total: file.cases.length, passed: file.cases.length - failures.length, failed: failures.length, failures: failures };
}
