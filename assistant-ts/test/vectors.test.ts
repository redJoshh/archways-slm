// Every vector in tests/vectors/assistant_vectors.json must match exactly.
// ASSISTANT_VECTORS=<path> runs another copy of the file.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { checkResults, parseQueryReply } from "../src/contract.ts";
import { askAssistant, startQuestion, type Step, type StepInput } from "../src/flow.ts";
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
    let step: Step = startQuestion(vector.question, vector.now_ms);
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
        step = step.next(input(vector.case_tokens));
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
    const result = await askAssistant(vector.question, {
      nowMs: () => vector.now_ms,
      complete: (call) => reply(call.kind === "query" ? vector.query_reply : vector.answer_reply) as Promise<string>,
      search: () => reply(vector.search_reply),
      countTokens: () => reply(vector.case_tokens) as Promise<number>,
    });
    assert.equal(result.path, vector.expected.path);
    assert.equal(result.text, vector.expected.text);
    assert.deepEqual(result.codes, vector.expected.codes);
  });
}

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
