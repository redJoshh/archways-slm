// Every vector in tests/vectors/assistant_vectors.json must match exactly.
// ASSISTANT_VECTORS=<path> runs another copy of the file.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { checkResults, parseQueryReply } from "../src/contract.ts";
import { querySpeedState, speedState, updateAnswerSpeed, updateSpeed } from "../src/budget.ts";
import { askAssistant, startQuestion, type QuestionLog, type Step, type StepInput } from "../src/flow.ts";
import { answerSystem, answerUserMessage, casePart, querySystem, systemTurn, todayText } from "../src/render.ts";
import { runVectors, type VectorFile } from "../src/vectors.ts";

const path =
  process.env.ASSISTANT_VECTORS ??
  fileURLToPath(new URL("../../../../tests/vectors/assistant_vectors.json", import.meta.url));
const file: VectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the vector file is the expected format and not empty", () => {
  assert.equal(file.format, "archways assistant vectors v1");
  assert.ok(file.render.length >= 44);
  assert.ok(file.flow.length >= 20);
});

test("runVectors reports every vector passing", () => {
  const report = runVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.failed, 0);
});

for (const vector of file.today) {
  test(`today ${vector.now_ms}`, () => assert.equal(todayText(vector.now_ms), vector.today));
}

for (const vector of file.render) {
  test(`render ${vector.id}`, () => {
    const results = checkResults(vector.results);
    assert.equal(systemTurn(querySystem(vector.now_ms)), vector.query_prefix);
    assert.equal(systemTurn(querySystem(vector.now_ms)) + casePart(vector.question), vector.query_prompt);
    assert.equal(systemTurn(answerSystem(vector.now_ms)), vector.answer_prefix);
    assert.equal(answerUserMessage(vector.question, results), vector.answer_user);
    assert.equal(casePart(vector.answer_user), vector.answer_case_part);
    assert.equal(vector.answer_prefix + vector.answer_case_part, vector.answer_prompt);
  });
}

for (const vector of file.query) {
  test(`query ${JSON.stringify(vector.text).slice(0, 60)}`, () => {
    let actual: unknown = null;
    let ok = true;
    try {
      actual = parseQueryReply(vector.text);
    } catch (error) {
      ok = false;
    }
    assert.equal(ok, vector.ok);
    assert.deepEqual(actual, vector.arguments);
  });
}

for (const vector of file.results) {
  test(`results ${JSON.stringify(vector.value).slice(0, 60)}`, () => {
    let actual: unknown = null;
    let ok = true;
    try {
      actual = checkResults(vector.value);
    } catch (error) {
      ok = false;
    }
    assert.equal(ok, vector.ok);
    assert.deepEqual(actual, vector.rows);
  });
}

const THROWS = { throws: true };
function isThrows(value: unknown): boolean {
  return JSON.stringify(value) === JSON.stringify(THROWS);
}
function input(value: unknown): StepInput {
  return isThrows(value) ? { ok: false } : { ok: true, value: value };
}

for (const vector of file.flow) {
  test(`flow stepper ${vector.id}`, () => {
    const seed = vector.speed === null ? null : { promptTps: vector.speed.prompt_tps, genTps: vector.speed.gen_tps };
    let step: Step = startQuestion(vector.question, vector.now_ms, seed);
    const sent: string[] = [];
    while (step.kind !== "done") {
      if (step.kind === "query") {
        sent.push(step.call.prompt);
        step = step.next(input(vector.query_reply));
      } else if (step.kind === "search") {
        assert.deepEqual(step.arguments, vector.expected.arguments);
        step = step.next(input(vector.search_reply));
      } else if (step.kind === "count") {
        assert.equal(step.casePart, vector.expected.answer_case_part);
        step = step.next(input(vector.case_tokens), vector.elapsed_ms);
      } else {
        sent.push(step.call.prompt);
        assert.ok(step.call.prompt.indexOf(step.call.prefix) === 0);
        step = step.next(input(vector.answer_reply));
      }
    }
    assert.equal(step.outcome.path, vector.expected.path);
    assert.equal(step.outcome.text, vector.expected.text);
    assert.deepEqual(step.outcome.codes, vector.expected.codes);
    assert.deepEqual(step.trace.arguments, vector.expected.arguments);
    assert.equal(step.trace.queryPrompt, vector.expected.query_prompt);
    assert.equal(step.trace.answerPrompt, vector.expected.answer_prompt);
    if (vector.expected.query_prompt !== null) assert.equal(sent[0], vector.expected.query_prompt);
  });

  test(`flow driver ${vector.id}`, async () => {
    const reply = (value: unknown) =>
      isThrows(value) ? Promise.reject(new Error("scripted")) : Promise.resolve(value);
    // A scripted clock: the time so far becomes elapsed_ms once tokens are counted.
    let now = 0;
    const logs: QuestionLog[] = [];
    const seed = vector.speed === null ? null : { promptTps: vector.speed.prompt_tps, genTps: vector.speed.gen_tps };
    const result = await askAssistant(vector.question, {
      nowMs: () => vector.now_ms,
      clockMs: () => now,
      complete: (call) =>
        reply(call.kind === "query" ? vector.query_reply : vector.answer_reply).then((text) => ({
          text: text as string,
        })),
      search: () => reply(vector.search_reply),
      countTokens: () => {
        now = vector.elapsed_ms;
        return reply(vector.case_tokens) as Promise<number>;
      },
      speed: speedState(seed),
      log: (entry) => logs.push(entry),
    });
    assert.equal(result.path, vector.expected.path);
    assert.equal(result.text, vector.expected.text);
    assert.deepEqual(result.codes, vector.expected.codes);
    const budget = vector.expected.budget;
    assert.equal(result.budget ? result.budget.predictedMs : null, budget ? budget.predicted_ms : null);
    assert.equal(result.resultCount, vector.expected.result_count);
    assert.deepEqual(logs, [
      {
        path: vector.expected.path,
        rule: budget ? budget.rule : null,
        predictedMs: budget ? budget.predicted_ms : null,
        actualMs: result.actualMs,
        resultCount: vector.expected.result_count,
        caseTokens: result.caseTokens,
      },
    ]);
  });
}

test("answer-call timings update the speed; query-call timings do not", async () => {
  const vector = file.flow.find((v) => v.id === "time-fast-e2e-009")!;
  const speed = speedState({ promptTps: 60, genTps: 20 });
  const timings = { prompt_n: 394, prompt_per_second: 30, predicted_n: 39, predicted_per_second: 11 };
  const result = await askAssistant(vector.question, {
    nowMs: () => vector.now_ms,
    complete: (call) =>
      Promise.resolve(
        call.kind === "query"
          ? { text: vector.query_reply as string, timings: { ...timings, prompt_per_second: 999, prompt_n: 500 } }
          : { text: vector.answer_reply as string, timings: timings },
      ),
    search: () => Promise.resolve(vector.search_reply),
    countTokens: () => Promise.resolve(vector.case_tokens as number),
    speed: speed,
  });
  assert.equal(result.path, "answer");
  assert.deepEqual(speed.get(), { promptTps: 30, genTps: 11 });
});

test("query-call timings alone never change the speed", async () => {
  const vector = file.flow.find((v) => v.id === "time-fast-e2e-009")!;
  const speed = speedState({ promptTps: 60, genTps: 20 });
  const timings = { prompt_n: 500, prompt_per_second: 99, predicted_n: 40, predicted_per_second: 99 };
  await askAssistant(vector.question, {
    nowMs: () => vector.now_ms,
    complete: (call) =>
      Promise.resolve(
        call.kind === "query"
          ? { text: vector.query_reply as string, timings: timings }
          : { text: vector.answer_reply as string },
      ),
    search: () => Promise.resolve(vector.search_reply),
    countTokens: () => Promise.resolve(vector.case_tokens as number),
    speed: speed,
  });
  assert.deepEqual(speed.get(), { promptTps: 60, genTps: 20 });
});

test("no speed: the 200-token rule decides, and the log says so", async () => {
  const vector = file.flow.find((v) => v.id === "time-fast-e2e-009")!;
  const logs: QuestionLog[] = [];
  const result = await askAssistant(vector.question, {
    nowMs: () => vector.now_ms,
    complete: (call) =>
      Promise.resolve({ text: (call.kind === "query" ? vector.query_reply : vector.answer_reply) as string }),
    search: () => Promise.resolve(vector.search_reply),
    countTokens: () => Promise.resolve(vector.case_tokens as number),
    log: (entry) => logs.push(entry),
  });
  assert.equal(result.path, "budget_fallback");
  assert.equal(logs[0].rule, "tokens");
  assert.equal(logs[0].predictedMs, null);
  assert.equal(logs[0].resultCount, 3);
});

test("a throwing log never changes the result", async () => {
  const result = await askAssistant("", {
    nowMs: () => 0,
    complete: () => Promise.resolve({ text: "" }),
    search: () => Promise.resolve([]),
    countTokens: () => Promise.resolve(0),
    log: () => {
      throw new Error("disk full");
    },
  });
  assert.equal(result.path, "question_invalid");
});

test("non-finite rates are ignored (not expressible in the JSON vectors)", () => {
  const redmi = { promptTps: 28, genTps: 10.4 };
  for (const rate of [NaN, Infinity, -Infinity]) {
    const timings = { prompt_n: 200, prompt_per_second: rate, predicted_n: 20, predicted_per_second: rate };
    assert.deepEqual(updateSpeed(redmi, timings), redmi);
  }
});

test("the driver never rejects, even if a dependency throws synchronously", async () => {
  const result = await askAssistant("When is the fair?", {
    nowMs: () => 0,
    complete: () => {
      throw new Error("sync");
    },
    search: () => Promise.resolve([]),
    countTokens: () => Promise.resolve(0),
  });
  assert.equal(result.path, "query_error");
});

test("Redmi 2026-11-07: short not-found replies add up until the speed is known", async () => {
  const vector = file.flow.find((v) => v.id === "answer-not-found-sentence")!;
  const speed = speedState(null);
  const paths: string[] = [];
  for (const ms of [625, 630, 630]) {
    const timings = { prompt_n: 177, prompt_per_second: 25, predicted_n: 8, predicted_ms: ms, predicted_per_second: 8000 / ms };
    const result = await askAssistant(vector.question, {
      nowMs: () => vector.now_ms,
      complete: (call) =>
        Promise.resolve(
          call.kind === "query"
            ? { text: vector.query_reply as string, timings: { predicted_n: 9, predicted_ms: 1, predicted_per_second: 9000 } }
            : { text: vector.answer_reply as string, timings: timings },
        ),
      search: () => Promise.resolve(vector.search_reply),
      countTokens: () => Promise.resolve(vector.case_tokens as number),
      speed: speed,
    });
    paths.push(result.path);
    if (paths.length === 1) {
      // Query-call timings never add to the total.
      assert.deepEqual(speed.pending(), { n: 8, ms: 625 });
      assert.equal(speed.get()!.genTps, null);
    }
  }
  assert.deepEqual(paths, ["answer_not_found", "answer_not_found", "answer_not_found"]);
  assert.equal(speed.get()!.genTps, 16000 / 1255);
  assert.deepEqual(speed.pending(), { n: 8, ms: 630 });
});

test("non-finite predicted_ms is ignored (not expressible in the JSON vectors)", () => {
  const pending = { n: 8, ms: 600 };
  for (const ms of [NaN, Infinity, -Infinity]) {
    const timings = { predicted_n: 8, predicted_ms: ms, predicted_per_second: 12.8 };
    assert.deepEqual(updateAnswerSpeed(null, pending, timings), {
      speed: { promptTps: null, genTps: null },
      pending: pending,
    });
  }
});

test("the answer path shows the guarded reply above the results list", async () => {
  const vector = file.flow.find((v) => v.id === "answer")!;
  const result = await askAssistant(vector.question, {
    nowMs: () => vector.now_ms,
    complete: (call) =>
      Promise.resolve({ text: (call.kind === "query" ? vector.query_reply : vector.answer_reply) as string }),
    search: () => Promise.resolve(vector.search_reply),
    countTokens: () => Promise.resolve(vector.case_tokens as number),
  });
  assert.equal(result.path, "answer");
  assert.ok(result.text.startsWith((vector.answer_reply as string) + "\n\nThese announcements may help:\n- "));
});

test("query-call timings update only the query speed, never the answer speed", async () => {
  const vector = file.flow.find((v) => v.id === "time-fast-e2e-009")!;
  const speed = speedState({ promptTps: 60, genTps: 20 });
  const querySpeed = querySpeedState({ promptTps: 23.8, genTps: 14.2 });
  const queryTimings = { prompt_n: 300, prompt_per_second: 25, predicted_n: 15, predicted_per_second: 15 };
  await askAssistant(vector.question, {
    nowMs: () => vector.now_ms,
    complete: (call) =>
      Promise.resolve(
        call.kind === "query"
          ? { text: vector.query_reply as string, timings: queryTimings }
          : { text: vector.answer_reply as string },
      ),
    search: () => Promise.resolve(vector.search_reply),
    countTokens: () => Promise.resolve(vector.case_tokens as number),
    speed: speed,
    querySpeed: querySpeed,
  });
  assert.deepEqual(speed.get(), { promptTps: 60, genTps: 20 });
  assert.deepEqual(querySpeed.get(), { promptTps: 25, genTps: 15 });
});
