/**
 * Runs tests/vectors/guard_vectors.json against this guard. Pure (no Node
 * APIs), so the same code runs under Node, the Hermes CLI and the Gate 1
 * app on a phone.
 */

import { type Announcement, guard } from "./guard.ts";
import {
  FALLBACK_HEADER,
  GUARD_SPACES,
  LAST_RESORT_MESSAGE,
  NON_ASCII_DIGIT_RANGES,
} from "./spec.ts";

export interface Vector {
  id: string;
  sources: string[];
  input: {
    question: string;
    results: Announcement[];
    forbidden: string[];
    reply: string;
    now: string | null;
  };
  expected: { fired: boolean; codes: string[]; text: string };
}

export interface VectorFile {
  format: string;
  spec: {
    guard_spaces: number[];
    non_ascii_digit_ranges: number[][];
    fallback_header: string;
    last_resort_message: string;
  };
  vectors: Vector[];
}

export interface VectorReport {
  total: number;
  passed: number;
  failed: number;
  /** Spec lists or messages that differ from the vector file. */
  specProblems: string[];
  /** Up to maxFailures failing vectors, with what this guard returned. */
  failures: { id: string; expected: Vector["expected"]; actual: Vector["expected"] }[];
}

/** The parity check for one vector: fired, codes and text must match. */
export function check(vector: Vector): { ok: boolean; actual: Vector["expected"] } {
  const { reply, results, question, forbidden } = vector.input;
  const result = guard(reply, results, question, forbidden);
  const actual = { fired: result.fired, codes: result.codes, text: result.text };
  const ok =
    actual.fired === vector.expected.fired &&
    actual.text === vector.expected.text &&
    JSON.stringify(actual.codes) === JSON.stringify(vector.expected.codes);
  return { ok, actual };
}

export function specProblems(file: VectorFile): string[] {
  const problems: string[] = [];
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  if (!same(GUARD_SPACES, file.spec.guard_spaces)) problems.push("guard_spaces");
  if (!same(NON_ASCII_DIGIT_RANGES, file.spec.non_ascii_digit_ranges)) {
    problems.push("non_ascii_digit_ranges");
  }
  if (FALLBACK_HEADER !== file.spec.fallback_header) problems.push("fallback_header");
  if (LAST_RESORT_MESSAGE !== file.spec.last_resort_message) {
    problems.push("last_resort_message");
  }
  return problems;
}

export function runVectors(file: VectorFile, maxFailures = 10): VectorReport {
  const report: VectorReport = {
    total: file.vectors.length,
    passed: 0,
    failed: 0,
    specProblems: specProblems(file),
    failures: [],
  };
  for (const vector of file.vectors) {
    let outcome: { ok: boolean; actual: Vector["expected"] };
    try {
      outcome = check(vector);
    } catch (error) {
      outcome = { ok: false, actual: { fired: false, codes: ["threw"], text: String(error) } };
    }
    if (outcome.ok) {
      report.passed++;
    } else {
      report.failed++;
      if (report.failures.length < maxFailures) {
        report.failures.push({ id: vector.id, expected: vector.expected, actual: outcome.actual });
      }
    }
  }
  return report;
}
