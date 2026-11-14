// rank_v1 (accuracy-phase.md) against the hand-written tests/vectors/rank_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { createFeedIndex, makeFeedSearch } from "../src/feedIndex.ts";
import { rankScorer } from "../src/rank.ts";
import { runRankVectors, type RankVectorFile } from "../src/rankVectors.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/rank_vectors.json", import.meta.url));
const file: RankVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the rank vector file is the expected format", () => {
  assert.equal(file.format, "archways rank vectors v1");
  assert.equal(file.rank, "rank_v1");
  assert.equal(file.cases.length, 11);
});

test("runRankVectors reports every rank vector passing", () => {
  const report = runRankVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 11 * 5);
});

test("rankScorer: null keeps newest first, an unknown version throws", () => {
  assert.equal(rankScorer(null, "anything"), undefined);
  assert.throws(() => rankScorer("rank_v2" as "rank_v1", "q"));
});

test("makeFeedSearch with rank needs the question; without rank it ignores it", async () => {
  const index = createFeedIndex(async () => ({ content: [], last: true }));
  const ranked = makeFeedSearch(index, () => 0, "rank_v1");
  await assert.rejects(ranked({ query: "x" }));
  assert.deepEqual(await ranked({ query: "x" }, { question: "x?" }), []);
  const plain = makeFeedSearch(index, () => 0);
  assert.deepEqual(await plain({ query: "x" }), []);
});
