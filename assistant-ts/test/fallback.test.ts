// window_v1 (docs/plans/window-fallback.md) against the hand-written
// tests/vectors/window_fallback_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { createFeedIndex, makeFeedSearch } from "../src/feedIndex.ts";
import { FALLBACK_DAYS, searchWithFallback } from "../src/fallback.ts";
import { runFallbackVectors, type FallbackVectorFile } from "../src/fallbackVectors.ts";
import { DAYS_MAX } from "../src/generated.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/window_fallback_vectors.json", import.meta.url));
const file: FallbackVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the fallback vector file is the expected format", () => {
  assert.equal(file.format, "archways window fallback vectors v1");
  assert.equal(file.window, "window_v1");
  assert.equal(file.rank, "rank_v1");
  assert.equal(file.matcher, "and_v4");
  assert.equal(file.fallback_days, FALLBACK_DAYS);
  assert.equal(DAYS_MAX, 30);
  assert.equal(file.cases.length, 12);
});

test("runFallbackVectors reports every fallback vector passing", () => {
  const report = runFallbackVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 12);
});

test("searchWithFallback off is the first search only", () => {
  const calls: (number | undefined)[] = [];
  const found = searchWithFallback((d) => (calls.push(d), []), { query: "x", days: 30 }, null);
  assert.deepEqual(found, { results: [], fellBack: false });
  assert.deepEqual(calls, [undefined]);
  assert.throws(() => searchWithFallback(() => [], { query: "x", days: 30 }, "window_v2" as never));
});

test("makeFeedSearch: window_v1 refuses retry, and reports fellBack", async () => {
  const index = createFeedIndex(async () => ({ content: [], last: true }));
  assert.throws(() => makeFeedSearch(index, () => 0, "rank_v1", "retry_v1", undefined, "and_v3", null, "window_v1"));
  const seen: { retried: boolean; fellBack: boolean; count: number }[] = [];
  const on = makeFeedSearch(index, () => 0, "rank_v1", null, (info) => seen.push(info), "and_v4", null, "window_v1");
  assert.deepEqual(await on({ query: "x", days: 30 }, { question: "x?" }), []);
  assert.deepEqual(await on({ query: "x", days: 7 }, { question: "x?" }), []);
  const off = makeFeedSearch(index, () => 0, "rank_v1", null, (info) => seen.push(info), "and_v4", null, null);
  await off({ query: "x", days: 30 }, { question: "x?" });
  const unranked = makeFeedSearch(index, () => 0, null, null, (info) => seen.push(info), "and_v3", null, "window_v1");
  await unranked({ query: "x", days: 30 });
  assert.deepEqual(seen, [
    { retried: false, fellBack: true, count: 0 },
    { retried: false, fellBack: false, count: 0 },
    { retried: false, fellBack: false, count: 0 },
    { retried: false, fellBack: true, count: 0 },
  ]);
});
