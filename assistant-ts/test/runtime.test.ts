// The model queue and the runtime (plan "model queue and speed recovery",
// 2026-11-10), against a fake llama.rn adapter that, like llama.rn, rejects
// a second completion while one is running.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { answerSpeedSuspect, querySpeedState, speedState } from "../src/budget.ts";
import { askAssistant, type QuestionLog } from "../src/flow.ts";
import { REMEASURE_MAX_PER_DAY, SUSPECT_RATIO } from "../src/generated.ts";
import { createModelQueue } from "../src/queue.ts";
import { createAssistantRuntime } from "../src/runtime.ts";
import { createFeedIndex } from "../src/feedIndex.ts";
import { MEASURE_TOKENS, type LlamaAdapter, type SessionSettings } from "../src/session.ts";
import type { VectorFile } from "../src/vectors.ts";

const path =
  process.env.ASSISTANT_VECTORS ??
  fileURLToPath(new URL("../../../../tests/vectors/assistant_vectors.json", import.meta.url));
const file: VectorFile = JSON.parse(readFileSync(path, "utf8"));
const VECTOR = file.flow.find((v) => v.id === "answer")!;

const SETTINGS: SessionSettings = {
  dir: "/data/app/models",
  modelSha256: "7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa",
  llamaRnVersion: "0.13.0-rc.8",
  nCtx: 2048,
  nThreads: 4,
};

interface Deferred {
  promise: Promise<void>;
  resolve: () => void;
}
function deferred(): Deferred {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((r) => (resolve = r));
  return { promise, resolve };
}

/** Lets every pending promise callback run. */
async function settle(rounds = 20): Promise<void> {
  for (let i = 0; i < rounds; i++) await Promise.resolve();
}

interface FakeOptions {
  /** Completions wait for this before returning (one gate per call, in order). */
  gates?: Deferred[];
  /** Generated tokens/s reported per call; defaults to 500. */
  genTps?: (prompt: string, measure: boolean) => number;
  /** Prompt tokens/s reported per call; defaults to 500. */
  promptTps?: (prompt: string, measure: boolean) => number;
}

interface Fake extends LlamaAdapter {
  calls: string[];
  concurrent: number;
}

function fakeLlama(options: FakeOptions = {}): Fake {
  const files: { [path: string]: number } = {};
  let running = false;
  let gateIndex = 0;
  const fake: Fake = {
    calls: [],
    concurrent: 0,
    countTokens: async (text) => Math.ceil(text.length / 4),
    completion: async (prompt, nPredict, measure) => {
      if (running) {
        fake.concurrent++;
        throw new Error("Context is busy");
      }
      running = true;
      try {
        const kind = prompt.indexOf("You turn a student") !== -1 ? "query" : "answer";
        fake.calls.push(kind + (measure ? " measure" : "") + " " + nPredict);
        const gate = options.gates ? options.gates[gateIndex++] : undefined;
        if (gate) await gate.promise;
        const isPriming = nPredict === 1 || !!measure;
        const text = isPriming ? "x" : kind === "query" ? (VECTOR.query_reply as string) : (VECTOR.answer_reply as string);
        const gen = options.genTps ? options.genTps(prompt, !!measure) : 500;
        return {
          text,
          timings: {
            prompt_n: Math.ceil(prompt.length / 4),
            prompt_per_second: options.promptTps ? options.promptTps(prompt, !!measure) : 500,
            predicted_n: measure ? MEASURE_TOKENS : isPriming ? 1 : 20,
            predicted_per_second: gen,
          },
        };
      } finally {
        running = false;
      }
    },
    saveSession: async (p, tokenSize) => {
      files[p] = tokenSize;
      return tokenSize;
    },
    loadSession: async (p) => files[p],
    fileExists: async (p) => Object.prototype.hasOwnProperty.call(files, p),
  };
  return fake;
}

// ---- queue ----

test("queue: jobs run one at a time, first in, first out", async () => {
  const queue = createModelQueue();
  const order: string[] = [];
  let active = 0;
  let maxActive = 0;
  const job = (name: string) => async () => {
    active++;
    maxActive = Math.max(maxActive, active);
    order.push("start " + name);
    await settle(3);
    order.push("end " + name);
    active--;
    return name;
  };
  const results = await Promise.all([queue.run(job("a")), queue.exclusive(job("b")), queue.run(job("c"))]);
  assert.deepEqual(
    results.map((r) => r.value),
    ["a", "b", "c"],
  );
  assert.equal(maxActive, 1);
  assert.deepEqual(order, ["start a", "end a", "start b", "end b", "start c", "end c"]);
});

test("queue: a rejected job does not stop the queue", async () => {
  const queue = createModelQueue();
  await assert.rejects(queue.run(() => Promise.reject(new Error("boom"))));
  const r = await queue.run(async () => 7);
  assert.equal(r.value, 7);
});

test("queue: an exclusive job waits for a running activity, and is not overlapped", async () => {
  const queue = createModelQueue();
  const end = await queue.beginActivity();
  let started = false;
  const done = queue.exclusive(async () => {
    started = true;
    return 1;
  });
  await settle();
  assert.equal(started, false);
  assert.equal(queue.busy(), true);
  end();
  const r = await done;
  assert.equal(started, true);
  assert.equal(r.overlap, false);
  assert.equal(queue.busy(), false);
});

test("queue: a new activity waits while an exclusive job is queued or running", async () => {
  const queue = createModelQueue();
  const gate = deferred();
  const done = queue.exclusive(() => gate.promise);
  let begun = false;
  const activity = queue.beginActivity().then((end) => {
    begun = true;
    return end;
  });
  await settle();
  assert.equal(begun, false);
  gate.resolve();
  const r = await done;
  assert.equal(r.overlap, false);
  (await activity)();
  assert.equal(begun, true);
});

test("queue: a run job overlapped by an activity says so", async () => {
  const queue = createModelQueue();
  const gate = deferred();
  const done = queue.run(() => gate.promise);
  await settle();
  const end = await queue.beginActivity();
  gate.resolve();
  assert.equal((await done).overlap, true);
  end();
  // An activity already running when the job starts also counts.
  const end2 = await queue.beginActivity();
  assert.equal((await queue.run(async () => 1)).overlap, true);
  end2();
  assert.equal((await queue.run(async () => 1)).overlap, false);
});

test("queue: end() is idempotent", async () => {
  const queue = createModelQueue();
  const end = await queue.beginActivity();
  end();
  end();
  const r = await queue.exclusive(async () => 1);
  assert.equal(r.overlap, false);
});

// ---- the runtime ----

function search() {
  return Promise.resolve(VECTOR.search_reply);
}

test("a question asked during priming waits for it, instead of a query_error", async () => {
  const gates = [deferred(), deferred()]; // answer priming, query priming (measures)
  const llama = fakeLlama({ gates });
  const runtime = createAssistantRuntime({ llama, settings: SETTINGS });
  const priming = runtime.prime(VECTOR.now_ms);
  await settle();
  assert.equal(runtime.state(), "priming");

  const logs: QuestionLog[] = [];
  const asked = runtime.ask(VECTOR.question, { nowMs: () => VECTOR.now_ms, search, log: (e) => logs.push(e) });
  await settle();
  // No query call has started: only the answer priming call so far.
  assert.deepEqual(llama.calls, ["answer 1"]);

  gates[0].resolve();
  await settle();
  assert.deepEqual(llama.calls, ["answer 1", "query measure " + MEASURE_TOKENS]);
  gates[1].resolve();
  await priming;

  const result = await asked;
  assert.equal(llama.concurrent, 0);
  assert.equal(result.path, "answer");
  assert.deepEqual(llama.calls.slice(2), ["query 64", "answer 200"]);
  assert.equal(logs.length, 1);
  assert.equal(logs[0].path, "answer");
  assert.equal(runtime.state(), "ready");
});

test("the wait is logged and kept out of the question's time", async () => {
  const gates = [deferred(), deferred()];
  let now = 1000;
  const llama = fakeLlama({ gates });
  const runtime = createAssistantRuntime({ llama, settings: SETTINGS, clockMs: () => now });
  const priming = runtime.prime(VECTOR.now_ms);
  const logs: QuestionLog[] = [];
  const asked = runtime.ask(VECTOR.question, { nowMs: () => VECTOR.now_ms, search, log: (e) => logs.push(e) });
  await settle();
  now = 9000; // priming took 8 s
  gates[0].resolve();
  gates[1].resolve();
  await priming;
  const result = await asked;
  assert.equal(result.readyWaitMs, 8000);
  assert.equal(logs[0].readyWaitMs, 8000);
  assert.equal(result.actualMs, 0); // the scripted clock did not move after the wait
});

test("without a runtime, two concurrent questions on one context still collide (the old bug)", async () => {
  const gate = deferred();
  const llama = fakeLlama({ gates: [gate] });
  const first = llama.completion("x".repeat(40), 1, false);
  await assert.rejects(llama.completion("y".repeat(40), 1, false), /busy/);
  gate.resolve();
  await first;
  assert.equal(llama.concurrent, 1);
});

test("two questions at once through the runtime never overlap model calls", async () => {
  const llama = fakeLlama();
  const runtime = createAssistantRuntime({ llama, settings: SETTINGS });
  await runtime.prime(VECTOR.now_ms);
  const extra = { nowMs: () => VECTOR.now_ms, search };
  const [a, b] = await Promise.all([runtime.ask(VECTOR.question, extra), runtime.ask(VECTOR.question, extra)]);
  assert.equal(llama.concurrent, 0);
  assert.equal(a.path, "answer");
  assert.equal(b.path, "answer");
});

test("priming is exclusive: the feed index build waits, and the samples are clean", async () => {
  const gates = [deferred(), deferred()];
  const llama = fakeLlama({ gates });
  const runtime = createAssistantRuntime({ llama, settings: SETTINGS });
  const fetched: string[] = [];
  const index = createFeedIndex(
    async (p: string) => {
      fetched.push(p);
      return { content: [], last: true };
    },
    { activity: runtime.beginActivity },
  );
  const priming = runtime.prime(VECTOR.now_ms);
  await settle();
  const build = index.rebuild();
  await settle();
  assert.deepEqual(fetched, []); // waits for priming
  gates[0].resolve();
  gates[1].resolve();
  const reports = await priming;
  await build;
  assert.ok(fetched.length >= 1);
  assert.deepEqual(
    reports.map((r) => r.overlap),
    [false, false],
  );
});

test("an index build already running delays priming; nothing overlaps", async () => {
  const llama = fakeLlama();
  const runtime = createAssistantRuntime({ llama, settings: SETTINGS });
  const end = await runtime.beginActivity();
  const priming = runtime.prime(VECTOR.now_ms);
  await settle();
  assert.deepEqual(llama.calls, []);
  end();
  const reports = await priming;
  assert.deepEqual(
    reports.map((r) => r.overlap),
    [false, false],
  );
});

test("an overlapped answer call does not update the speed", async () => {
  const speed = speedState({ promptTps: 60, genTps: 20 });
  const querySpeed = querySpeedState({ promptTps: 50, genTps: 14 });
  const timings = { prompt_n: 394, prompt_per_second: 30, predicted_n: 39, predicted_per_second: 3 };
  await askAssistant(VECTOR.question, {
    nowMs: () => VECTOR.now_ms,
    complete: (call) =>
      Promise.resolve({
        text: (call.kind === "query" ? VECTOR.query_reply : VECTOR.answer_reply) as string,
        timings,
        overlap: true,
      }),
    search,
    countTokens: () => Promise.resolve(VECTOR.case_tokens as number),
    speed,
    querySpeed,
  });
  assert.deepEqual(speed.get(), { promptTps: 60, genTps: 20 });
  assert.deepEqual(querySpeed.get(), { promptTps: 50, genTps: 14 });
});

// ---- re-measure ----

test("a suspect answer speed is re-measured once, and the clean measurement replaces it", async () => {
  // Priming measures 6.7 generated tokens/s (the Redmi 2026-11-10 sample) and
  // a slow prompt rate, so the question falls back before any answer call (as
  // on the Redmi, where the answer speed then never corrects). Its query call
  // runs at 13.6; the re-measure then measures 12.0.
  let phase = "priming";
  const llama = fakeLlama({
    genTps: (_prompt, measure) => (phase === "priming" ? 6.7 : measure ? 12.0 : 13.6),
    promptTps: () => (phase === "priming" ? 5 : 500),
  });
  const remeasures: number[] = [];
  const runtime = createAssistantRuntime({
    llama,
    settings: SETTINGS,
    onRemeasure: (r) => remeasures.push((r.timings as { predicted_per_second: number }).predicted_per_second),
  });
  await runtime.prime(VECTOR.now_ms);
  // Answer gen borrowed the query measuring call's 6.7; query gen 6.7 too: not suspect yet.
  assert.equal(runtime.speed().get()!.genTps, 6.7);
  assert.equal(runtime.state(), "ready");
  phase = "questions";
  const first = await runtime.ask(VECTOR.question, { nowMs: () => VECTOR.now_ms, search });
  assert.equal(first.path, "budget_fallback");
  assert.equal(llama.calls.filter((c) => c === "answer 200").length, 0);
  // The query call measured 13.6: 6.7 < 0.6 * 13.6, so a re-measure is queued.
  assert.equal(runtime.state(), "measuring");
  await runtime.whenReady();
  assert.deepEqual(remeasures, [12.0]);
  assert.equal(runtime.speed().get()!.genTps, 12.0);
  assert.equal(runtime.remeasuresOn(VECTOR.now_ms), 1);
  assert.ok(llama.calls.indexOf("answer measure " + MEASURE_TOKENS) !== -1);
  // 12.0 >= 0.6 * 13.6: not suspect any more, so no second re-measure.
  assert.equal(await runtime.remeasureIfNeeded(VECTOR.now_ms), null);
  assert.equal(runtime.remeasuresOn(VECTOR.now_ms), 1);
});

test("a re-measure that confirms a slow phone is kept, and the day limit stops further ones", async () => {
  let phase = "priming";
  const llama = fakeLlama({ genTps: (_p, measure) => (phase === "priming" ? 14 : measure ? 5 : 14) });
  const runtime = createAssistantRuntime({ llama, settings: SETTINGS });
  await runtime.prime(VECTOR.now_ms);
  // Force a suspect answer speed (as if an answer call had measured 3).
  runtime.speed().update({ prompt_n: 300, prompt_per_second: 500, predicted_n: 20, predicted_per_second: 3 });
  phase = "questions";
  for (let i = 0; i < REMEASURE_MAX_PER_DAY + 2; i++) await runtime.remeasureIfNeeded(VECTOR.now_ms);
  assert.equal(runtime.remeasuresOn(VECTOR.now_ms), REMEASURE_MAX_PER_DAY);
  assert.equal(runtime.speed().get()!.genTps, 5); // the measured truth, still low
  assert.equal(
    llama.calls.filter((c) => c === "answer measure " + MEASURE_TOKENS).length,
    REMEASURE_MAX_PER_DAY,
  );
  // A new Manila day allows re-measures again.
  const nextDay = VECTOR.now_ms + 24 * 3600 * 1000;
  assert.equal(runtime.remeasuresOn(nextDay), 0);
});

test("a re-measure is exclusive: an index build asked for meanwhile waits, and a question too", async () => {
  let phase = "priming";
  const gates = [deferred(), deferred(), deferred()];
  gates[0].resolve();
  gates[1].resolve(); // priming runs freely; the re-measure (3rd call) is held
  const llama = fakeLlama({ gates, genTps: (_p, measure) => (phase === "priming" ? 14 : measure ? 12 : 14) });
  const runtime = createAssistantRuntime({ llama, settings: SETTINGS });
  await runtime.prime(VECTOR.now_ms);
  runtime.speed().update({ prompt_n: 300, prompt_per_second: 500, predicted_n: 20, predicted_per_second: 3 });
  phase = "questions";
  const measuring = runtime.remeasureIfNeeded(VECTOR.now_ms);
  await settle();
  assert.equal(runtime.state(), "measuring");
  let activityBegun = false;
  const activity = runtime.beginActivity().then((end) => {
    activityBegun = true;
    return end;
  });
  const asked = runtime.ask(VECTOR.question, { nowMs: () => VECTOR.now_ms, search });
  await settle();
  assert.equal(activityBegun, false);
  assert.equal(llama.calls.filter((c) => c.startsWith("query 64")).length, 0);
  gates[2].resolve();
  const report = await measuring;
  assert.equal(report!.overlap, false);
  assert.equal(runtime.speed().get()!.genTps, 12);
  (await activity)();
  assert.equal((await asked).path, "answer");
  assert.equal(llama.concurrent, 0);
});

test("the suspect rule matches the plan's numbers", () => {
  assert.equal(SUSPECT_RATIO, 0.6);
  assert.equal(answerSpeedSuspect({ promptTps: 30.7, genTps: 6.7 }, { promptTps: 29.9, genTps: 13.6 }), true);
  assert.equal(answerSpeedSuspect({ promptTps: 27.1, genTps: 10.4 }, { promptTps: 23.8, genTps: 14.6 }), false);
  assert.equal(answerSpeedSuspect(null, null), true);
});
