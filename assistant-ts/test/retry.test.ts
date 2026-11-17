// retry_v1 (accuracy-phase.md) against the hand-written tests/vectors/retry_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { createFeedIndex, makeFeedSearch } from "../src/feedIndex.ts";
import { runRetryVectors, type RetryVectorFile } from "../src/retryVectors.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/retry_vectors.json", import.meta.url));
const file: RetryVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the retry vector file is the expected format", () => {
  assert.equal(file.format, "archways retry vectors v1");
  assert.equal(file.retry, "retry_v1");
  assert.equal(file.cases.length, 9);
});

test("runRetryVectors reports every retry vector passing", () => {
  const report = runRetryVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 9);
});

test("makeFeedSearch: retry needs rank, and reports the flag and count", async () => {
  const index = createFeedIndex(async () => ({ content: [], last: true }));
  assert.throws(() => makeFeedSearch(index, () => 0, null, "retry_v1"));
  const seen: { retried: boolean; fellBack: boolean; count: number }[] = [];
  const search = makeFeedSearch(index, () => 0, "rank_v1", "retry_v1", (info) => seen.push(info), "and_v3", null, null);
  assert.deepEqual(await search({ query: "x" }, { question: "Where is the library?" }), []);
  assert.deepEqual(seen, [{ retried: true, fellBack: false, count: 0 }]);
});
