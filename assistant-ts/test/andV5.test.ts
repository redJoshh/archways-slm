// and_v5 (v2 fix (e), the Taglish lexicon v1) against the hand-written
// tests/vectors/and_v5_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { runAndV5Vectors, type AndV5VectorFile } from "../src/andV5Vectors.ts";
import { SYNONYMS_V2, SYNONYMS_V3 } from "../src/searchData.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/and_v5_vectors.json", import.meta.url));
const file: AndV5VectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the and_v5 vector file is the expected format", () => {
  assert.equal(file.format, "archways and_v5 vectors v1");
  assert.equal(file.matcher, "and_v5");
  assert.equal(file.cases.length, 10);
});

test("runAndV5Vectors reports every vector passing under and_v5 and and_v4", () => {
  const report = runAndV5Vectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 20);
});

test("SYNONYMS_V3 is SYNONYMS_V2 plus 98 lexicon terms", () => {
  for (const key of Object.keys(SYNONYMS_V2)) assert.deepEqual(SYNONYMS_V3[key], SYNONYMS_V2[key]);
  assert.equal(Object.keys(SYNONYMS_V3).length - Object.keys(SYNONYMS_V2).length, 98);
});
