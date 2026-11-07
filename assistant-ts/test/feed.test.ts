// The on-phone feed search (ADR 0006) against tests/vectors/feed_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { runFeedVectors, type FeedVectorFile } from "../src/feedVectors.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/feed_vectors.json", import.meta.url));
const file: FeedVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the feed vector file is the expected format", () => {
  assert.equal(file.format, "archways feed search vectors v1");
  assert.equal(file.matcher, "and_v3");
  assert.ok(file.search.cases.length >= 60);
});

test("runFeedVectors reports every feed vector passing", () => {
  const report = runFeedVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.failed, 0);
  assert.ok(report.total > 150);
});
