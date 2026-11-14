// excerpt_v2_centred (accuracy-phase.md (e)) against tests/vectors/window_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { createFeedIndex, makeFeedSearch } from "../src/feedIndex.ts";
import { runWindowVectors, type WindowVectorFile } from "../src/windowVectors.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/window_vectors.json", import.meta.url));
const file: WindowVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("runWindowVectors reports every window vector passing", () => {
  assert.equal(file.format, "archways window vectors v1");
  const report = runWindowVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 15);
});

test("makeFeedSearch: the window refuses retry and needs the question", async () => {
  const index = createFeedIndex(async () => ({ content: [], last: true }));
  assert.throws(() => makeFeedSearch(index, () => 0, "rank_v1", "retry_v1", undefined, "and_v3", "excerpt_v2_centred"));
  const search = makeFeedSearch(index, () => 0, "rank_v1", null, undefined, "and_v4", "excerpt_v2_centred");
  await assert.rejects(search({ query: "x" }));
  assert.deepEqual(await search({ query: "x" }, { question: "x?" }), []);
});
