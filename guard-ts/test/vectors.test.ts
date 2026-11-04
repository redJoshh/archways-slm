// Every vector in tests/vectors/guard_vectors.json must match exactly.
// GUARD_VECTORS=<path> runs another copy of the file.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { check, runVectors, specProblems, type VectorFile } from "../src/runVectors.ts";

const path =
  process.env.GUARD_VECTORS ??
  fileURLToPath(new URL("../../../tests/vectors/guard_vectors.json", import.meta.url));
const file: VectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the vector file is the expected format and not empty", () => {
  assert.equal(file.format, "archways guard vectors v1");
  assert.ok(file.vectors.length > 400, `only ${file.vectors.length} vectors`);
});

test("spec lists and messages match the vector file", () => {
  assert.deepEqual(specProblems(file), []);
});

test("runVectors reports every vector passing", () => {
  const report = runVectors(file);
  assert.equal(report.failed, 0, JSON.stringify(report.failures, null, 1));
  assert.equal(report.passed, file.vectors.length);
});

for (const vector of file.vectors) {
  test(`${vector.id} ${vector.sources[0]}`, () => {
    const { actual } = check(vector);
    assert.deepEqual(actual, vector.expected);
  });
}
