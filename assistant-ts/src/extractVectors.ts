/**
 * Runs tests/vectors/extract_vectors.json (v2 fix (d)) against the port,
 * without node APIs, so the same check runs under node and Hermes: each
 * step's expected value, then the flow (extract_v1 and past_date_v1 on):
 * the extract text, or, with no quote, the normal answer path.
 */

import { EXTRACT_LABEL, extractQuote } from "./extract.ts";
import { resultsList, startQuestion, type Step } from "./flow.ts";
import type { Announcement } from "./render.ts";

export interface ExtractVectorFile {
  format: string;
  rule: "extract_v1";
  label: string;
  cases: {
    name: string;
    question: string;
    now: string;
    results: Announcement[];
    classified: boolean;
    words: string[] | null;
    admissible: boolean;
    sentences: string[] | null;
    guard_fired: boolean;
    quote: string | null;
    codes: string[];
  }[];
}

export interface ExtractVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

const EXTRACT_VECTOR_QUERY = '{"query": "schedule", "days": 30}';
const EXTRACT_VECTOR_REPLY = "It is on the date in the announcement.";

function extractSame(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Drives the flow with scripted steps; returns the final step. */
export function runExtractFlow(question: string, nowMs: number, results: Announcement[]): Step {
  let step = startQuestion(question, nowMs, null, { extract: "extract_v1", pastDate: "past_date_v1" });
  while (step.kind !== "done") {
    if (step.kind === "query") step = step.next({ ok: true, value: EXTRACT_VECTOR_QUERY });
    else if (step.kind === "search") step = step.next({ ok: true, value: results });
    else if (step.kind === "count") step = step.next({ ok: true, value: 150 }, 0);
    else step = step.next({ ok: true, value: EXTRACT_VECTOR_REPLY });
  }
  return step;
}

export function runExtractVectors(file: ExtractVectorFile): ExtractVectorReport {
  const failures: string[] = [];
  let total = 0;
  for (const c of file.cases) {
    total++;
    try {
      const found = extractQuote(c.question, c.results);
      if (
        found.classified !== c.classified ||
        !extractSame(found.words, c.words) ||
        found.admissible !== c.admissible ||
        !extractSame(found.sentences, c.sentences) ||
        found.guardFired !== c.guard_fired
      ) {
        failures.push("extract steps " + c.name);
        continue;
      }
      const step = runExtractFlow(c.question, Date.parse(c.now), c.results);
      if (step.kind !== "done") throw new Error("not done");
      const outcome = step.outcome;
      if (c.quote === null) {
        if (outcome.path !== "answer" || step.trace.answerPrompt === null) failures.push("extract flow " + c.name);
        continue;
      }
      const text = EXTRACT_LABEL + "\n" + c.quote + "\n\n" + resultsList(c.results);
      if (
        outcome.path !== "extract" ||
        outcome.text !== text ||
        !extractSame(outcome.codes, c.codes) ||
        outcome.budget !== null ||
        outcome.resultCount !== c.results.length ||
        step.trace.answerPrompt !== null
      ) {
        failures.push("extract flow " + c.name);
      }
    } catch (error) {
      failures.push("extract threw " + c.name);
    }
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
