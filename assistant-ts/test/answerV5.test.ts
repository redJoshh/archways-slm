// answer_v5 (v2 fix (f), compact_v5) against the hand-written
// tests/vectors/answer_v5_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { runAnswerV5Vectors, type AnswerV5VectorFile } from "../src/answerV5Vectors.ts";
import { ANSWER_PROMPT_TEXT } from "../src/generated.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/answer_v5_vectors.json", import.meta.url));
const file: AnswerV5VectorFile = JSON.parse(readFileSync(path, "utf8"));
const v5 = fileURLToPath(new URL("../../../../prompts/e2e_answer_v5.txt", import.meta.url));

test("the answer_v5 vector file is the expected format", () => {
  assert.equal(file.format, "archways answer_v5 vectors v1");
  assert.equal(file.rule, "compact_v5");
  assert.equal(file.cases.length, 3);
});

test("runAnswerV5Vectors: every message, and the flow sends it", () => {
  const report = runAnswerV5Vectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 3);
});

test("prompt v5 is the phone's answer prompt text (v1's bytes)", () => {
  assert.equal(readFileSync(v5, "utf8"), ANSWER_PROMPT_TEXT);
});
