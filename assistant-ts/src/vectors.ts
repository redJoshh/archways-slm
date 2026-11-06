/**
 * Runs tests/vectors/assistant_vectors.json against the port, without node
 * APIs, so the same check runs under node and under the Hermes CLI.
 */

import { checkResults, parseQueryReply } from "./contract.ts";
import { startQuestion, type Step, type StepInput } from "./flow.ts";
import { answerSystem, answerUserMessage, casePart, querySystem, systemTurn, todayText } from "./render.ts";

export interface FlowExpected {
  path: string;
  text: string;
  codes: string[];
  arguments: unknown;
  query_prompt: string | null;
  answer_case_part: string | null;
  answer_prompt: string | null;
}

export interface VectorFile {
  format: string;
  today: { now_ms: number; today: string }[];
  render: {
    id: string;
    now_ms: number;
    question: string;
    results: unknown;
    query_prefix: string;
    query_prompt: string;
    answer_prefix: string;
    answer_user: string;
    answer_case_part: string;
    answer_prompt: string;
  }[];
  query: { text: string; ok: boolean; arguments: unknown }[];
  results: { value: unknown; ok: boolean; rows: unknown }[];
  flow: {
    id: string;
    now_ms: number;
    question: string;
    query_reply: unknown;
    search_reply: unknown;
    case_tokens: unknown;
    answer_reply: unknown;
    expected: FlowExpected;
  }[];
}

export interface VectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

// Key-order-insensitive deep equality for JSON values.
function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a as object);
  const kb = Object.keys(b as object);
  if (ka.length !== kb.length) return false;
  for (const key of ka) {
    if (!Object.prototype.hasOwnProperty.call(b, key)) return false;
    if (!same((a as { [k: string]: unknown })[key], (b as { [k: string]: unknown })[key])) return false;
  }
  return true;
}

function attempt<T>(run: () => T): { ok: boolean; value: T | null } {
  try {
    return { ok: true, value: run() };
  } catch (error) {
    return { ok: false, value: null };
  }
}

function input(value: unknown): StepInput {
  const throws =
    typeof value === "object" && value !== null && (value as { throws?: unknown }).throws === true;
  return throws ? { ok: false } : { ok: true, value: value };
}

export function runVectors(file: VectorFile, maxFailures = 20): VectorReport {
  const failures: string[] = [];
  let total = 0;
  let failed = 0;
  const record = (label: string, ok: boolean) => {
    total++;
    if (ok) return;
    failed++;
    if (failures.length < maxFailures) failures.push(label);
  };

  for (const v of file.today) record("today " + v.now_ms, todayText(v.now_ms) === v.today);
  for (const v of file.render) {
    const rows = attempt(() => checkResults(v.results));
    const ok =
      rows.ok &&
      systemTurn(querySystem(v.now_ms)) === v.query_prefix &&
      systemTurn(querySystem(v.now_ms)) + casePart(v.question) === v.query_prompt &&
      systemTurn(answerSystem(v.now_ms)) === v.answer_prefix &&
      answerUserMessage(v.question, rows.value || []) === v.answer_user &&
      casePart(v.answer_user) === v.answer_case_part &&
      v.answer_prefix + v.answer_case_part === v.answer_prompt;
    record("render " + v.id, ok);
  }
  for (const v of file.query) {
    const got = attempt(() => parseQueryReply(v.text));
    record("query " + JSON.stringify(v.text), got.ok === v.ok && same(got.value, v.arguments));
  }
  for (const v of file.results) {
    const got = attempt(() => checkResults(v.value));
    record("results " + JSON.stringify(v.value).slice(0, 80), got.ok === v.ok && same(got.value, v.rows));
  }
  for (const v of file.flow) {
    let step: Step = startQuestion(v.question, v.now_ms);
    while (step.kind !== "done") {
      if (step.kind === "query") step = step.next(input(v.query_reply));
      else if (step.kind === "search") step = step.next(input(v.search_reply));
      else if (step.kind === "count") step = step.next(input(v.case_tokens));
      else step = step.next(input(v.answer_reply));
    }
    const e = v.expected;
    const ok =
      step.outcome.path === e.path &&
      step.outcome.text === e.text &&
      same(step.outcome.codes, e.codes) &&
      same(step.trace.arguments, e.arguments) &&
      step.trace.queryPrompt === e.query_prompt &&
      step.trace.answerCasePart === e.answer_case_part &&
      step.trace.answerPrompt === e.answer_prompt;
    record("flow " + v.id, ok);
  }
  return { total: total, passed: total - failed, failed: failed, failures: failures };
}
