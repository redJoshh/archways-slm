/**
 * The assistant runtime (plan "model queue and speed recovery", 2026-11-10):
 * the one object an app wires up. It owns the model queue (queue.ts), the
 * answer and query speeds, priming and the answer-speed re-measure.
 *
 * - prime(nowMs): primes the sessions, each call an exclusive queue job
 *   (nothing else runs; the feed index waits). Reports overlapped by other
 *   work are ignored by speedsFromPriming(). State: "priming", then a
 *   re-measure if needed, then "ready".
 * - ask(question, extra): askAssistant() with deps() (every model call and
 *   token count through the queue; the question waits for readiness instead
 *   of failing), then remeasureIfNeeded() in the background.
 * - remeasureIfNeeded(nowMs): if answerSpeedSuspect(answer, query) (the
 *   answer generation rate is unknown, or below SUSPECT_RATIO times the
 *   query's), one exclusive primeOne(answer, measure) job. Its timings update
 *   the answer speed only if nothing overlapped it. At most
 *   REMEASURE_MAX_PER_DAY per Manila day, one at a time. A valid re-measure
 *   is the truth even if it is still low.
 * - beginActivity(): for the app's other CPU work (createFeedIndex's
 *   activity option).
 * - state()/onChange(): "not_primed" | "priming" | "measuring" | "ready", for
 *   a "getting ready" message.
 */

import { answerSpeedSuspect, querySpeedState, speedsFromPriming, speedState, type SpeedState } from "./budget.ts";
import { askAssistant, type AssistantDeps, type AssistantResult } from "./flow.ts";
import { REMEASURE_MAX_PER_DAY } from "./generated.ts";
import { createModelQueue, type ModelQueue } from "./queue.ts";
import { todayText } from "./render.ts";
import {
  makeComplete,
  primeOne,
  primeSessions,
  type LlamaAdapter,
  type PrimeReport,
  type SessionSettings,
} from "./session.ts";

export type RuntimeState = "not_primed" | "priming" | "measuring" | "ready";

export interface RuntimeOptions {
  llama: LlamaAdapter;
  settings: SessionSettings;
  clockMs?: () => number;
  /** Optional: told about each re-measure (numbers only). Errors are ignored. */
  onRemeasure?: (report: PrimeReport) => void;
}

export type RuntimeDeps = Pick<
  AssistantDeps,
  "complete" | "countTokens" | "speed" | "querySpeed" | "whenReady" | "clockMs"
>;

export interface AssistantRuntime {
  readonly queue: ModelQueue;
  state(): RuntimeState;
  onChange(listener: () => void): () => void;
  prime(nowMs: number): Promise<PrimeReport[]>;
  whenReady(): Promise<void>;
  beginActivity(): Promise<() => void>;
  speed(): SpeedState;
  querySpeed(): SpeedState;
  deps(): RuntimeDeps;
  ask(question: string, extra: Omit<AssistantDeps, keyof RuntimeDeps>): Promise<AssistantResult>;
  remeasureIfNeeded(nowMs: number): Promise<PrimeReport | null>;
  /** Re-measures started on the Manila day of nowMs. */
  remeasuresOn(nowMs: number): number;
}

function manilaDay(nowMs: number): string {
  return todayText(nowMs).split(", ")[1];
}

export function createAssistantRuntime(options: RuntimeOptions): AssistantRuntime {
  const llama = options.llama;
  const settings = options.settings;
  const clock = options.clockMs || Date.now;
  const queue = createModelQueue();
  let speed = speedState(null);
  let querySpeed = querySpeedState(null);
  let primed = false;
  let priming = false;
  let measuring = false;
  let remeasureDay = "";
  let remeasureCount = 0;
  const waiters: (() => void)[] = [];
  const listeners: (() => void)[] = [];

  function ready(): boolean {
    return !priming && !measuring;
  }

  function changed(): void {
    if (ready()) {
      const release = waiters.splice(0, waiters.length);
      release.forEach((resolve) => resolve());
    }
    for (const listener of listeners.slice()) {
      try {
        listener();
      } catch (error) {
        // A listener never breaks the runtime.
      }
    }
  }

  function whenReady(): Promise<void> {
    if (ready()) return Promise.resolve();
    return new Promise<void>((resolve) => waiters.push(resolve));
  }

  function remeasuresOn(nowMs: number): number {
    return remeasureDay === manilaDay(nowMs) ? remeasureCount : 0;
  }

  async function remeasureIfNeeded(nowMs: number): Promise<PrimeReport | null> {
    if (!primed || priming || measuring) return null;
    if (!answerSpeedSuspect(speed.get(), querySpeed.get())) return null;
    const day = manilaDay(nowMs);
    if (remeasureDay !== day) {
      remeasureDay = day;
      remeasureCount = 0;
    }
    if (remeasureCount >= REMEASURE_MAX_PER_DAY) return null;
    remeasureCount++;
    measuring = true;
    changed();
    let report: PrimeReport | null = null;
    try {
      const done = await queue.exclusive(() => primeOne(llama, settings, "answer", nowMs, clock, true));
      report = { ...done.value, overlap: done.overlap };
      if (!done.overlap) speed.update(report.timings);
    } catch (error) {
      report = null; // a failed re-measure changes nothing; it still counts
    } finally {
      measuring = false;
      changed();
    }
    if (report && options.onRemeasure) {
      try {
        options.onRemeasure(report);
      } catch (error) {
        // Reporting never changes the runtime.
      }
    }
    return report;
  }

  const complete = makeComplete(llama, settings, queue);
  const countTokens = async function (text: string): Promise<number> {
    return (await queue.run(() => llama.countTokens(text))).value;
  };

  function deps(): RuntimeDeps {
    return {
      complete: complete,
      countTokens: countTokens,
      speed: speed,
      querySpeed: querySpeed,
      whenReady: whenReady,
      clockMs: clock,
    };
  }

  return {
    queue: queue,
    state: () => (priming ? "priming" : measuring ? "measuring" : primed ? "ready" : "not_primed"),
    onChange: (listener) => {
      listeners.push(listener);
      return () => {
        const i = listeners.indexOf(listener);
        if (i !== -1) listeners.splice(i, 1);
      };
    },
    prime: async function (nowMs: number) {
      priming = true;
      changed();
      let reports: PrimeReport[] = [];
      try {
        reports = await primeSessions(llama, settings, nowMs, clock, queue);
        const speeds = speedsFromPriming(reports);
        speed = speedState(speeds.answer);
        querySpeed = querySpeedState(speeds.query);
        primed = true;
        remeasureDay = manilaDay(nowMs);
        remeasureCount = 0;
      } finally {
        priming = false;
        changed();
      }
      await remeasureIfNeeded(nowMs);
      return reports;
    },
    whenReady: whenReady,
    beginActivity: () => queue.beginActivity(),
    speed: () => speed,
    querySpeed: () => querySpeed,
    deps: deps,
    ask: async function (question, extra) {
      const result = await askAssistant(question, { ...extra, ...deps() });
      // In the background: the caller has its answer already.
      remeasureIfNeeded(extra.nowMs()).catch(() => undefined);
      return result;
    },
    remeasureIfNeeded: remeasureIfNeeded,
    remeasuresOn: remeasuresOn,
  };
}
