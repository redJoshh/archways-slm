/**
 * Runs tests/vectors/answer_v5_vectors.json (v2 fix (f), compact_v5) against
 * the port, without node APIs, so the same check runs under node and Hermes:
 * the exact user message, and that the flow sends it with answerFormat.
 */

import { checkResults } from "./contract.ts";
import { startQuestion } from "./flow.ts";
import { compactAnswerUserMessage, type Announcement } from "./render.ts";

export interface AnswerV5VectorFile {
  format: string;
  rule: "compact_v5";
  cases: { name: string; question: string; results: Announcement[]; expected: string }[];
}

export interface AnswerV5VectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runAnswerV5Vectors(file: AnswerV5VectorFile): AnswerV5VectorReport {
  const failures: string[] = [];
  let total = 0;
  for (const c of file.cases) {
    total++;
    try {
      const results = checkResults(c.results);
      if (compactAnswerUserMessage(c.question, results) !== c.expected) {
        failures.push("answer_v5 message " + c.name);
        continue;
      }
      let step = startQuestion(c.question, Date.parse("2026-11-19T10:00:00+08:00"), null, {
        answerFormat: "compact_v5",
      });
      if (step.kind === "query") step = step.next({ ok: true, value: '{"query": "enrollment", "days": 30}' });
      if (step.kind === "search") step = step.next({ ok: true, value: c.results });
      if (step.kind !== "count" || step.casePart.indexOf(c.expected) === -1) {
        failures.push("answer_v5 flow " + c.name);
      }
    } catch (error) {
      failures.push("answer_v5 threw " + c.name);
    }
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
