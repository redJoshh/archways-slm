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
 * - over budget (budget.ts: predicted time over 15 s, or over 200 tokens
 *   while this phone's speed is unknown, or over the n_ctx limit)
 *                                                        -> resultsList(results)
 * - token count, answer call or guard failed             -> resultsList(results)
 * - guard fired                                          -> resultsList(results)
 * - the reply is exactly NOT_FOUND_MESSAGE (after the ASCII trim), although
 *   results exist ("answer_not_found")                   -> resultsList(results)
 * - the guard passed the reply ("answer")
 *              -> reply + ANSWER_LIST_SEPARATOR + resultsList(results)
 * resultsList() is RESULTS_HEADER and fallback()'s lines (titles and posted
 * dates): every path with results ends with it (ADR 0004, UAT configuration,
 * 2026-11-07). If it can't be built, the text is LAST_RESORT_MESSAGE.
 */

import { fallback, guard } from "../../guard-ts/src/guard.ts";
import { decideBudget, type Budget, type Speed, type SpeedState } from "./budget.ts";
import {
  ANSWER_LIST_SEPARATOR,
  FALLBACK_HEADER,
  LAST_RESORT_MESSAGE,
  NOT_FOUND_MESSAGE,
  RESULTS_HEADER,
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
  | "answer_not_found"
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
  /** The budget decision; null if no answer call was considered. */
  budget: Budget | null;
  /** Accepted search results; null if no search result was accepted. */
  resultCount: number | null;
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
  /** elapsedMs: the question's time so far (query call, search, counting). */
  | { kind: "count"; casePart: string; next: (input: StepInput, elapsedMs: number) => Step }
  | { kind: "answer"; call: ModelCall; next: (input: StepInput) => Step }
  | { kind: "done"; outcome: Outcome; trace: Trace };

/** RESULTS_HEADER, then fallback()'s lines (a port of results_list()). */
export function resultsList(results: Announcement[]): string {
  const text = fallback(results);
  if (text.indexOf(FALLBACK_HEADER + "\n") !== 0) throw new Error("fallback() changed its header line");
  return RESULTS_HEADER + text.slice(FALLBACK_HEADER.length);
}

function safeResultsList(results: Announcement[]): string | null {
  try {
    return resultsList(results);
  } catch (error) {
    return null;
  }
}

function listOrLastResort(results: Announcement[]): string {
  const listed = safeResultsList(results);
  return listed === null ? LAST_RESORT_MESSAGE : listed;
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= 0;
}

/** speed: this phone's measured rates (null or omitted: unknown). */
export function startQuestion(question: string, nowMs: number, speed?: Speed | null): Step {
  const trace: Trace = {
    arguments: null,
    queryPrompt: null,
    answerPrompt: null,
    answerCasePart: null,
    results: null,
  };
  let resultCount: number | null = null;
  let budget: Budget | null = null;
  const done = (path: Path, text: string, codes?: string[]): Step => ({
    kind: "done",
    outcome: { path: path, text: text, codes: codes || [], budget: budget, resultCount: resultCount },
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
      return done("answer_error", listOrLastResort(results));
    }
    const reply = trimAscii(input.value);
    // The not-found sentence although results exist: show the list instead.
    if (reply === NOT_FOUND_MESSAGE) return done("answer_not_found", listOrLastResort(results));
    let guarded: { fired: boolean; text: string; codes: string[] };
    try {
      guarded = guard(reply, results, question, []);
    } catch (error) {
      // Defense in depth: never show an unguarded reply.
      return done("answer_error", listOrLastResort(results));
    }
    const listed = safeResultsList(results);
    if (guarded.fired) {
      return done("guard_fired", listed === null ? LAST_RESORT_MESSAGE : listed, guarded.codes.slice());
    }
    // Unreachable for contract-checked results; never show the reply without its list.
    if (listed === null) return done("answer_error", LAST_RESORT_MESSAGE);
    return done("answer", guarded.text + ANSWER_LIST_SEPARATOR + listed, guarded.codes.slice());
  };

  const afterCount = (results: Announcement[], call: ModelCall) => (input: StepInput, elapsedMs: number): Step => {
    if (!input.ok || !isCount(input.value)) return done("answer_error", listOrLastResort(results));
    budget = decideBudget(input.value, elapsedMs, speed);
    if (budget.fallback) return done("budget_fallback", listOrLastResort(results));
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
    resultCount = results.length;
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

/** One model call's result: its text, and llama.rn's timings if reported. */
export interface Completion {
  text: string;
  timings?: unknown;
}

/**
 * The per-question UAT log entry: never the question or any text. The app
 * must keep these for UAT, to report how often the 15 s bar held.
 */
export interface QuestionLog {
  path: Path;
  /** "time", "tokens", "n_ctx", or null if no answer call was considered. */
  rule: Budget["rule"] | null;
  predictedMs: number | null;
  actualMs: number;
  resultCount: number | null;
  caseTokens: number | null;
}

export interface AssistantDeps {
  /** The current instant in ms since the epoch (Date.now in the app). */
  nowMs: () => number;
  /** Runs one model call (see session.ts makeComplete). */
  complete: (call: ModelCall) => Promise<Completion>;
  /** Calls Spring's search_announcements with these arguments; returns the JSON. */
  search: (args: SearchArguments) => Promise<unknown>;
  /** Qwen tokens in text: llama.rn context.tokenize(text).tokens.length. */
  countTokens: (text: string) => Promise<number>;
  /** Monotonic-ish clock for timings; defaults to Date.now. */
  clockMs?: () => number;
  /**
   * This phone's speed (budget.ts speedState, seeded from priming). Each
   * answer call's timings update it. Omitted: unknown, the 200-token rule.
   */
  speed?: SpeedState;
  /** Called once per question with the UAT log entry. Errors are ignored. */
  log?: (entry: QuestionLog) => void;
}

export interface AssistantResult extends Outcome {
  /** ms per step: query, search, count, answer (only the steps that ran). */
  timings: { [step: string]: number };
  /** The whole question, from askAssistant() to the final text. */
  actualMs: number;
  caseTokens: number | null;
  trace: Trace;
}

/** One question, end to end. Never rejects; always returns text to show. */
export async function askAssistant(question: string, deps: AssistantDeps): Promise<AssistantResult> {
  const clock = deps.clockMs || Date.now;
  const begun = clock();
  const timings: { [step: string]: number } = {};
  let caseTokens: number | null = null;
  let result: AssistantResult;
  try {
    let step = startQuestion(question, deps.nowMs(), deps.speed ? deps.speed.get() : null);
    while (step.kind !== "done") {
      const started = clock();
      let input: StepInput;
      try {
        let value: unknown;
        if (step.kind === "query" || step.kind === "answer") {
          const completion = await deps.complete(step.call);
          value = completion.text;
          // Only answer calls update the speed: query replies are short and
          // generate faster (14.6 against 10.4 tokens/s on the Redmi 10C).
          if (step.kind === "answer" && deps.speed) deps.speed.update(completion.timings);
        } else if (step.kind === "search") value = await deps.search(step.arguments);
        else {
          value = await deps.countTokens(step.casePart);
          if (typeof value === "number") caseTokens = value;
        }
        input = { ok: true, value: value };
      } catch (error) {
        input = { ok: false };
      }
      timings[step.kind] = clock() - started;
      step = step.kind === "count" ? step.next(input, clock() - begun) : step.next(input);
    }
    result = {
      path: step.outcome.path,
      text: step.outcome.text,
      codes: step.outcome.codes,
      budget: step.outcome.budget,
      resultCount: step.outcome.resultCount,
      timings: timings,
      actualMs: clock() - begun,
      caseTokens: caseTokens,
      trace: step.trace,
    };
  } catch (error) {
    // The stepper itself failed (a bug): show nothing from the model.
    result = {
      path: "answer_error",
      text: LAST_RESORT_MESSAGE,
      codes: [],
      budget: null,
      resultCount: null,
      timings: timings,
      actualMs: clock() - begun,
      caseTokens: caseTokens,
      trace: { arguments: null, queryPrompt: null, answerPrompt: null, answerCasePart: null, results: null },
    };
  }
  if (deps.log) {
    try {
      deps.log({
        path: result.path,
        rule: result.budget ? result.budget.rule : null,
        predictedMs: result.budget ? result.budget.predictedMs : null,
        actualMs: result.actualMs,
        resultCount: result.resultCount,
        caseTokens: result.caseTokens,
      });
    } catch (error) {
      // Logging must never change what the user sees.
    }
  }
  return result;
}
