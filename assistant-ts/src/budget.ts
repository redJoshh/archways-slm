/**
 * The adaptive time budget (ADR 0004, UAT configuration): a port of
 * update_speed(), predict_ms() and decide_budget() in
 * src/archways_assistant/assistant.py.
 *
 * A UAT product setting, not a Gate 1 bar: Gate 1 is still measured on the
 * Redmi 10C (15 s, e2e-009, still FAIL).
 *
 * Before the answer call, after the search:
 *   predicted = elapsedMs + ANSWER_LOAD_MS + caseTokens * 1000 / promptTps
 *             + GEN_TOKENS * 1000 / genTps + OVERHEAD_MS
 * - case part over CASE_TOKENS_CTX_MAX         -> fallback ("n_ctx")
 * - speed unknown (either rate missing)        -> the 200-token rule ("tokens")
 * - otherwise fallback iff predicted > BAR_MS  ("time")
 * The order of operations is part of the spec: Python and TS agree exactly.
 *
 * Speed comes from llama.rn completion timings: the priming calls (folded in
 * order, so the last one's rates win) and then each answer call. A rate is
 * used only if it is a finite number in RATE_MIN..RATE_MAX tokens/s and came
 * from at least PROMPT_N_MIN prompt / PREDICTED_N_MIN generated tokens.
 * Speed is never saved: after an app restart with existing session files it
 * is unknown until the first answer call reports timings.
 */

import {
  ANSWER_LOAD_MS,
  BAR_MS,
  BUDGET_CASE_TOKENS,
  CASE_TOKENS_CTX_MAX,
  GEN_TOKENS,
  OVERHEAD_MS,
  PREDICTED_N_MIN,
  PROMPT_N_MIN,
  RATE_MAX,
  RATE_MIN,
} from "./generated.ts";

/** This phone's measured rates in tokens/s; null means not measured. */
export interface Speed {
  promptTps: number | null;
  genTps: number | null;
}

export interface KnownSpeed {
  promptTps: number;
  genTps: number;
}

export type BudgetRule = "time" | "tokens" | "n_ctx";

export interface Budget {
  rule: BudgetRule;
  fallback: boolean;
  /** The predicted whole question in ms; null unless rule is "time". */
  predictedMs: number | null;
}

function acceptRate(rate: unknown, count: unknown, countMin: number): rate is number {
  return (
    typeof rate === "number" &&
    isFinite(rate) &&
    rate >= RATE_MIN &&
    rate <= RATE_MAX &&
    typeof count === "number" &&
    count >= countMin
  );
}

function field(value: object, key: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(value, key)) return undefined;
  return (value as { [key: string]: unknown })[key];
}

/** speed with each rate replaced by the timings' rate if that one is usable. */
export function updateSpeed(speed: Speed | null | undefined, timings: unknown): Speed {
  let promptTps = speed ? speed.promptTps : null;
  let genTps = speed ? speed.genTps : null;
  if (typeof timings === "object" && timings !== null && !Array.isArray(timings)) {
    const prompt = field(timings, "prompt_per_second");
    if (acceptRate(prompt, field(timings, "prompt_n"), PROMPT_N_MIN)) promptTps = prompt;
    const gen = field(timings, "predicted_per_second");
    if (acceptRate(gen, field(timings, "predicted_n"), PREDICTED_N_MIN)) genTps = gen;
  }
  return { promptTps: promptTps, genTps: genTps };
}

export function speedKnown(speed: Speed | null | undefined): speed is KnownSpeed {
  return !!speed && speed.promptTps !== null && speed.genTps !== null;
}

export function predictMs(caseTokens: number, elapsedMs: number, speed: KnownSpeed): number {
  return (
    elapsedMs +
    ANSWER_LOAD_MS +
    (caseTokens * 1000) / speed.promptTps +
    (GEN_TOKENS * 1000) / speed.genTps +
    OVERHEAD_MS
  );
}

export function decideBudget(caseTokens: number, elapsedMs: number, speed: Speed | null | undefined): Budget {
  if (caseTokens > CASE_TOKENS_CTX_MAX) return { rule: "n_ctx", fallback: true, predictedMs: null };
  if (!speedKnown(speed)) {
    return { rule: "tokens", fallback: caseTokens > BUDGET_CASE_TOKENS, predictedMs: null };
  }
  const predicted = predictMs(caseTokens, elapsedMs, speed);
  return { rule: "time", fallback: predicted > BAR_MS, predictedMs: predicted };
}

/** The speed the app holds between questions, in memory only. */
export interface SpeedState {
  get: () => Speed | null;
  update: (timings: unknown) => void;
}

export function speedState(initial?: Speed | null): SpeedState {
  let current: Speed | null = initial || null;
  return {
    get: () => current,
    update: (timings: unknown) => {
      current = updateSpeed(current, timings);
    },
  };
}
