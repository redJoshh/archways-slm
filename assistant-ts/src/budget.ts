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
 * is unknown until answer calls report enough generated tokens.
 *
 * Answer calls go through updateAnswerSpeed() (speedState().update): a reply
 * shorter than PREDICTED_N_MIN tokens (the 8-token not-found sentence) adds
 * its predicted_n and predicted_ms to a running total; at PREDICTED_N_MIN
 * tokens the total becomes the generation rate. Priming never adds to it.
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

/** Generated tokens and ms of short answer replies, not yet a rate. */
export interface Pending {
  n: number;
  ms: number;
}

function isIntegralNumber(value: unknown): value is number {
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value;
}

/** 1 to PREDICTED_N_MIN - 1 tokens (integral), in finite, positive ms. */
function isShortSample(count: unknown, ms: unknown): count is number {
  return (
    isIntegralNumber(count) &&
    count >= 1 &&
    count < PREDICTED_N_MIN &&
    typeof ms === "number" &&
    isFinite(ms) &&
    ms > 0
  );
}

/**
 * updateSpeed() for an answer call, adding up short replies (a port of
 * update_answer_speed()). Answer calls only, never priming or query calls.
 */
export function updateAnswerSpeed(
  speed: Speed | null | undefined,
  pending: Pending,
  timings: unknown,
): { speed: Speed; pending: Pending } {
  const updated = updateSpeed(speed, timings);
  if (typeof timings !== "object" || timings === null || Array.isArray(timings)) {
    return { speed: updated, pending: pending };
  }
  const count = field(timings, "predicted_n");
  if (acceptRate(field(timings, "predicted_per_second"), count, PREDICTED_N_MIN)) {
    return { speed: updated, pending: { n: 0, ms: 0 } };
  }
  const ms = field(timings, "predicted_ms");
  if (!isShortSample(count, ms)) return { speed: updated, pending: pending };
  const total: Pending = { n: pending.n + count, ms: pending.ms + (ms as number) };
  if (total.n < PREDICTED_N_MIN) return { speed: updated, pending: total };
  const rate = (total.n * 1000) / total.ms;
  const speedOut = acceptRate(rate, total.n, PREDICTED_N_MIN)
    ? { promptTps: updated.promptTps, genTps: rate }
    : updated;
  return { speed: speedOut, pending: { n: 0, ms: 0 } };
}

/**
 * The speed the app holds between questions, in memory only. update() is
 * for answer-call timings: it keeps the running total of short replies.
 */
export interface SpeedState {
  get: () => Speed | null;
  update: (timings: unknown) => void;
  /** The running total of short answer replies (for logs and tests). */
  pending: () => Pending;
}

export function speedState(initial?: Speed | null): SpeedState {
  let current: Speed | null = initial || null;
  let pending: Pending = { n: 0, ms: 0 };
  return {
    get: () => current,
    update: (timings: unknown) => {
      const next = updateAnswerSpeed(current, pending, timings);
      current = next.speed;
      pending = next.pending;
    },
    pending: () => ({ n: pending.n, ms: pending.ms }),
  };
}
