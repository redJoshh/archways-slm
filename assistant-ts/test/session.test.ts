// Session priming and makeComplete() against a fake llama.rn adapter.
import assert from "node:assert/strict";
import { test } from "node:test";

import { ANSWER_PROMPT_SHA256, QUERY_PROMPT_SHA256 } from "../src/generated.ts";
import { casePart } from "../src/render.ts";
import {
  makeComplete,
  MEASURE_TOKENS,
  N_PREDICT,
  primeSessions,
  sessionFile,
  sessionPrefix,
  speedFromPriming,
  type LlamaAdapter,
  type SessionSettings,
} from "../src/session.ts";
import { startQuestion } from "../src/flow.ts";

const SETTINGS: SessionSettings = {
  dir: "/data/app/models/",
  modelSha256: "7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa",
  llamaRnVersion: "0.13.0-rc.8",
  nCtx: 2048,
  nThreads: 4,
};
const FRIDAY = Date.parse("2026-11-06T10:00:00+08:00");
const SATURDAY_MIDNIGHT = Date.parse("2026-11-07T00:00:00+08:00");

interface FakeLlama extends LlamaAdapter {
  log: string[];
  files: { [path: string]: number };
}

// Tokens = characters / 4, rounded up: deterministic, not Qwen's count.
function fakeLlama(options: { shortLoad?: number } = {}): FakeLlama {
  const files: { [path: string]: number } = {};
  const log: string[] = [];
  let shortLoads = options.shortLoad || 0;
  return {
    files,
    log,
    countTokens: async (text) => Math.ceil(text.length / 4),
    completion: async (prompt, nPredict, measure) => {
      log.push("completion " + nPredict + " " + prompt.length + (measure ? " measure" : ""));
      const text = prompt.indexOf("search") !== -1 && nPredict === N_PREDICT.query ? '{"query": "x"}' : "ok";
      const timings = {
        prompt_n: Math.ceil(prompt.length / 4),
        prompt_per_second: measure ? 28 : 9,
        predicted_n: nPredict,
        predicted_per_second: 10.4,
      };
      return { text: text, timings: timings };
    },
    saveSession: async (path, tokenSize) => {
      log.push("save " + path + " " + tokenSize);
      files[path] = tokenSize;
      return tokenSize;
    },
    loadSession: async (path) => {
      log.push("load " + path);
      if (shortLoads > 0) {
        shortLoads--;
        return files[path] - 1;
      }
      return files[path];
    },
    fileExists: async (path) => Object.prototype.hasOwnProperty.call(files, path),
  };
}

test("session file names encode everything the saved state depends on", () => {
  const answer = sessionFile("answer", SETTINGS, FRIDAY);
  assert.equal(
    answer,
    "/data/app/models/answer-p" +
      ANSWER_PROMPT_SHA256.slice(0, 12) +
      "-2026-11-06-m7f4030143c1c-rn0.13.0_rc.8-c2048-t4.session",
  );
  assert.ok(sessionFile("query", SETTINGS, FRIDAY).indexOf("query-p" + QUERY_PROMPT_SHA256.slice(0, 12)) !== -1);
  assert.notEqual(sessionFile("answer", SETTINGS, SATURDAY_MIDNIGHT), answer);
  assert.notEqual(sessionFile("answer", { ...SETTINGS, nThreads: 8 }, FRIDAY), answer);
  assert.notEqual(sessionFile("answer", { ...SETTINGS, modelSha256: "00" + SETTINGS.modelSha256 }, FRIDAY), answer);
});

test("prefixes carry the Manila date, so a new day needs new files", () => {
  assert.ok(sessionPrefix("answer", FRIDAY).indexOf("Today is Friday, 2026-11-06 (Asia/Manila).") !== -1);
  assert.ok(sessionPrefix("query", SATURDAY_MIDNIGHT).indexOf("Today is Saturday, 2026-11-07") !== -1);
});

test("primeSessions saves both prefixes once, with their own token counts", async () => {
  const llama = fakeLlama();
  const first = await primeSessions(llama, SETTINGS, FRIDAY);
  assert.deepEqual(
    first.map((r) => r.kind),
    ["answer", "query"],
  );
  for (const report of first) {
    assert.equal(report.tokens, Math.ceil(sessionPrefix(report.kind, FRIDAY).length / 4));
    assert.equal(llama.files[report.file], report.tokens);
  }
  // Primed with the prefix plus an empty user turn: one token for the first
  // call, MEASURE_TOKENS with ignore_eos for the last (it measures the speed).
  assert.ok(llama.log.indexOf("completion 1 " + (sessionPrefix("answer", FRIDAY) + casePart("")).length) !== -1);
  assert.ok(
    llama.log.indexOf(
      "completion " + MEASURE_TOKENS + " " + (sessionPrefix("query", FRIDAY) + casePart("")).length + " measure",
    ) !== -1,
  );
  assert.deepEqual(await primeSessions(llama, SETTINGS, FRIDAY), []);
  assert.equal((await primeSessions(llama, SETTINGS, SATURDAY_MIDNIGHT)).length, 2);
});

test("speedFromPriming takes the last priming call's rates", async () => {
  const llama = fakeLlama();
  const reports = await primeSessions(llama, SETTINGS, FRIDAY);
  // The fake reports 9 prompt tokens/s for the first call (like the Redmi's
  // first call after load) and 28 for the measuring one.
  assert.deepEqual(speedFromPriming(reports), { promptTps: 28, genTps: 10.4 });
  // Files already there (an app restart): nothing primed, speed unknown.
  const again = await primeSessions(llama, SETTINGS, FRIDAY);
  assert.equal(speedFromPriming(again), null);
});

test("when only one kind needs priming, that call measures", async () => {
  const llama = fakeLlama();
  await primeSessions(llama, SETTINGS, FRIDAY);
  delete llama.files[sessionFile("answer", SETTINGS, FRIDAY)];
  llama.log.length = 0;
  const reports = await primeSessions(llama, SETTINGS, FRIDAY);
  assert.deepEqual(
    reports.map((r) => r.kind),
    ["answer"],
  );
  assert.ok(llama.log.some((line) => line.endsWith(" measure")));
  assert.deepEqual(speedFromPriming(reports), { promptTps: 28, genTps: 10.4 });
});

test("priming without timings leaves the speed unknown", async () => {
  const llama = fakeLlama();
  const plain = { ...llama, completion: async () => ({ text: "ok" }) };
  const reports = await primeSessions(plain, SETTINGS, FRIDAY);
  assert.deepEqual(speedFromPriming(reports), { promptTps: null, genTps: null });
});

test("makeComplete loads the call's own session, then runs the whole prompt", async () => {
  const llama = fakeLlama();
  await primeSessions(llama, SETTINGS, FRIDAY);
  llama.log.length = 0;
  const complete = makeComplete(llama, SETTINGS);
  const step = startQuestion("When is the fair?", FRIDAY);
  assert.equal(step.kind, "query");
  if (step.kind !== "query") return;
  await complete(step.call);
  assert.deepEqual(llama.log, [
    "load " + sessionFile("query", SETTINGS, FRIDAY),
    "completion " + N_PREDICT.query + " " + step.call.prompt.length,
  ]);
});

test("makeComplete primes a missing file first", async () => {
  const llama = fakeLlama();
  const step = startQuestion("When is the fair?", FRIDAY);
  if (step.kind !== "query") throw new Error("expected a query step");
  await makeComplete(llama, SETTINGS)(step.call);
  const file = sessionFile("query", SETTINGS, FRIDAY);
  assert.deepEqual(
    llama.log.map((line) => line.split(" ")[0]),
    ["completion", "save", "load", "completion"],
  );
  assert.ok(llama.files[file] > 0);
});

test("makeComplete re-primes once when a load comes back short, then gives up", async () => {
  const step = startQuestion("When is the fair?", FRIDAY);
  if (step.kind !== "query") throw new Error("expected a query step");

  const once = fakeLlama({ shortLoad: 1 });
  await primeSessions(once, SETTINGS, FRIDAY);
  assert.equal((await makeComplete(once, SETTINGS)(step.call)).text, '{"query": "x"}');

  const always = fakeLlama({ shortLoad: 2 });
  await primeSessions(always, SETTINGS, FRIDAY);
  await assert.rejects(makeComplete(always, SETTINGS)(step.call), /loaded/);
});

test("makeComplete rejects a call whose prompt is not its prefix's", async () => {
  const llama = fakeLlama();
  const step = startQuestion("When is the fair?", FRIDAY);
  if (step.kind !== "query") throw new Error("expected a query step");
  await assert.rejects(
    makeComplete(llama, SETTINGS)({ ...step.call, prompt: "x" + step.call.prompt }),
    /prefix/,
  );
  await assert.rejects(
    makeComplete(llama, SETTINGS)({ ...step.call, nowMs: SATURDAY_MIDNIGHT }),
    /prefix/,
  );
});
