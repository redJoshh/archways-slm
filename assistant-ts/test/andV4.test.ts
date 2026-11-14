// and_v4 (accuracy-phase.md section 3 (c)) against the hand-written tests/vectors/and_v4_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { createFeedIndex, makeFeedSearch } from "../src/feedIndex.ts";
import { runAndV4Vectors, type AndV4VectorFile } from "../src/andV4Vectors.ts";
import { SYNONYMS, SYNONYMS_V2 } from "../src/searchData.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/and_v4_vectors.json", import.meta.url));
const file: AndV4VectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the and_v4 vector file is the expected format", () => {
  assert.equal(file.format, "archways and_v4 vectors v1");
  assert.equal(file.matcher, "and_v4");
  assert.equal(file.cases.length, 7);
});

test("runAndV4Vectors reports every vector passing under and_v4 and and_v3", () => {
  const report = runAndV4Vectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 14);
});

test("SYNONYMS_V2 is SYNONYMS plus pasok only", () => {
  const rest: { [word: string]: readonly string[] } = {};
  for (const key of Object.keys(SYNONYMS_V2)) if (key !== "pasok") rest[key] = SYNONYMS_V2[key];
  assert.deepEqual(rest, SYNONYMS);
  assert.deepEqual(SYNONYMS_V2["pasok"], ["class"]);
});

test("makeFeedSearch: retry_v1 refuses and_v4", () => {
  const index = createFeedIndex(async () => ({ content: [], last: true }));
  assert.throws(() => makeFeedSearch(index, () => 0, "rank_v1", "retry_v1", undefined, "and_v4"));
  assert.doesNotThrow(() => makeFeedSearch(index, () => 0, "rank_v1", null, undefined, "and_v4"));
});
