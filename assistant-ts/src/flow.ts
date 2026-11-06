/**
 * The on-device question flow (ADR 0004, UAT configuration): a port of
 * flow() in src/archways_assistant/assistant.py.
 *
 *   question -> query call -> search (Spring, via the app) -> budget check
 *   -> answer call -> guard -> final text
 *
 * startQuestion() returns the first step. Each step names the work the app
 * must do; step.next() takes its result ({ ok: true, value } or
 * { ok: false } when it threw) and returns the next step, until "done".
 * The stepper is synchronous and pure, so the parity vectors drive it
 * directly. askAssistant() is the async driver the app calls.
 *
 * Failure rules (every path returns text; model text is shown only after
 * the guard passed it):
 * - invalid question, query call failed or invalid, search failed or
 *   broke the contract  -> LAST_RESORT_MESSAGE
 * - no results                                           -> NOT_FOUND_MESSAGE
 * - case part over BUDGET_CASE_TOKENS                    -> fallback(results)
 * - token count, answer call or guard failed             -> fallback(results)
 * - guard fired                                          -> the guard's text
 * fallback() failing gives LAST_RESORT_MESSAGE.
 */

import { fallback, guard } from "../../guard-ts/src/guard.ts";
import {
  BUDGET_CASE_TOKENS,
  LAST_RESORT_MESSAGE,
  NOT_FOUND_MESSAGE,
} from "./generated.ts";
import {
  checkQuestion,
  checkResults,
  parseQueryReply,
  type SearchArguments,
} from "./contract.ts";
import {
  answerSystem,
  answerUserMessage,
  casePart,
  querySystem,
  systemTurn,
  type Announcement,
} from "./render.ts";
import { trimAscii } from "./text.ts";

export type Path =
  | "answer"
  | "guard_fired"
  | "budget_fallback"
  | "answer_error"
  | "not_found"
  | "query_invalid"
  | "query_error"
  | "search_error"
  | "question_invalid";

export interface Outcome {
  path: Path;
  text: string;
  codes: string[];
}

export type StepInput = { ok: true; value: unknown } | { ok: false };

export interface Trace {
  arguments: SearchArguments | null;
  queryPrompt: string | null;
  answerPrompt: string | null;
  answerCasePart: string | null;
  results: Announcement[] | null;
}

export interface ModelCall {
  kind: "query" | "answer";
  /** The cached system turn; prompt starts with it. */
  prefix: string;
  /** The whole raw prompt for llama.rn. */
  prompt: string;
  /** The question's instant: the session files are per Manila day. */
  nowMs: number;
}

export type Step =
  | { kind: "query"; call: ModelCall; next: (input: StepInput) => Step }
  | { kind: "search"; arguments: SearchArguments; next: (input: StepInput) => Step }
  | { kind: "count"; casePart: string; next: (input: StepInput) => Step }
  | { kind: "answer"; call: ModelCall; next: (input: StepInput) => Step }
  | { kind: "done"; outcome: Outcome; trace: Trace };

function safeFallback(results: Announcement[]): string {
  try {
    return fallback(results);
  } catch (error) {
    return LAST_RESORT_MESSAGE;
  }
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= 0;
}

export function startQuestion(question: string, nowMs: number): Step {
  const trace: Trace = {
    arguments: null,
    queryPrompt: null,
    answerPrompt: null,
    answerCasePart: null,
    results: null,
  };
  const done = (path: Path, text: string, codes?: string[]): Step => ({
    kind: "done",
    outcome: { path: path, text: text, codes: codes || [] },
    trace: trace,
  });

  try {
    checkQuestion(question);
  } catch (error) {
    return done("question_invalid", LAST_RESORT_MESSAGE);
  }
  const qSystem = querySystem(nowMs);
  const qPrefix = systemTurn(qSystem);
  trace.queryPrompt = qPrefix + casePart(question);

  const afterAnswer = (results: Announcement[]) => (input: StepInput): Step => {
    if (!input.ok || typeof input.value !== "string") {
      return done("answer_error", safeFallback(results));
    }
    const reply = trimAscii(input.value);
    try {
      const guarded = guard(reply, results, question, []);
      return done(guarded.fired ? "guard_fired" : "answer", guarded.text, guarded.codes.slice());
    } catch (error) {
      // Defense in depth: never show an unguarded reply.
      return done("answer_error", safeFallback(results));
    }
  };

  const afterCount = (results: Announcement[], call: ModelCall) => (input: StepInput): Step => {
    if (!input.ok || !isCount(input.value)) return done("answer_error", safeFallback(results));
    if (input.value > BUDGET_CASE_TOKENS) return done("budget_fallback", safeFallback(results));
    return { kind: "answer", call: call, next: afterAnswer(results) };
  };

  const afterSearch = (input: StepInput): Step => {
    if (!input.ok) return done("search_error", LAST_RESORT_MESSAGE);
    let results: Announcement[];
    try {
      results = checkResults(input.value);
    } catch (error) {
      return done("search_error", LAST_RESORT_MESSAGE);
    }
    trace.results = results;
    if (results.length === 0) return done("not_found", NOT_FOUND_MESSAGE);
    const aPrefix = systemTurn(answerSystem(nowMs));
    const aCase = casePart(answerUserMessage(question, results));
    trace.answerCasePart = aCase;
    trace.answerPrompt = aPrefix + aCase;
    const call: ModelCall = { kind: "answer", prefix: aPrefix, prompt: aPrefix + aCase, nowMs: nowMs };
    return { kind: "count", casePart: aCase, next: afterCount(results, call) };
  };

  const afterQuery = (input: StepInput): Step => {
    if (!input.ok) return done("query_error", LAST_RESORT_MESSAGE);
    let args: SearchArguments;
    try {
      args = parseQueryReply(input.value);
    } catch (error) {
      return done("query_invalid", LAST_RESORT_MESSAGE);
    }
    trace.arguments = args;
    return { kind: "search", arguments: args, next: afterSearch };
  };

  return {
    kind: "query",
    call: { kind: "query", prefix: qPrefix, prompt: trace.queryPrompt, nowMs: nowMs },
    next: afterQuery,
  };
}

export interface AssistantDeps {
  /** The current instant in ms since the epoch (Date.now in the app). */
  nowMs: () => number;
  /** Runs one model call (see session.ts makeComplete) and returns its text. */
  complete: (call: ModelCall) => Promise<string>;
  /** Calls Spring's search_announcements with these arguments; returns the JSON. */
  search: (args: SearchArguments) => Promise<unknown>;
  /** Qwen tokens in text: llama.rn context.tokenize(text).tokens.length. */
  countTokens: (text: string) => Promise<number>;
  /** Monotonic-ish clock for timings; defaults to Date.now. */
  clockMs?: () => number;
}

export interface AssistantResult extends Outcome {
  /** ms per step: query, search, count, answer (only the steps that ran). */
  timings: { [step: string]: number };
  caseTokens: number | null;
  trace: Trace;
}

/** One question, end to end. Never rejects; always returns text to show. */
export async function askAssistant(question: string, deps: AssistantDeps): Promise<AssistantResult> {
  const clock = deps.clockMs || Date.now;
  const timings: { [step: string]: number } = {};
  let caseTokens: number | null = null;
  try {
    let step = startQuestion(question, deps.nowMs());
    while (step.kind !== "done") {
      const started = clock();
      let input: StepInput;
      try {
        let value: unknown;
        if (step.kind === "query" || step.kind === "answer") value = await deps.complete(step.call);
        else if (step.kind === "search") value = await deps.search(step.arguments);
        else {
          value = await deps.countTokens(step.casePart);
          if (typeof value === "number") caseTokens = value;
        }
        input = { ok: true, value: value };
      } catch (error) {
        input = { ok: false };
      }
      timings[step.kind] = clock() - started;
      step = step.next(input);
    }
    return {
      path: step.outcome.path,
      text: step.outcome.text,
      codes: step.outcome.codes,
      timings: timings,
      caseTokens: caseTokens,
      trace: step.trace,
    };
  } catch (error) {
    // The stepper itself failed (a bug): show nothing from the model.
    return {
      path: "answer_error",
      text: LAST_RESORT_MESSAGE,
      codes: [],
      timings: timings,
      caseTokens: caseTokens,
      trace: { arguments: null, queryPrompt: null, answerPrompt: null, answerCasePart: null, results: null },
    };
  }
}
