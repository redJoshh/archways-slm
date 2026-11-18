// contradiction_v1 (v2 fix (a)) against the hand-written
// tests/vectors/contradiction_vectors.json, and in the flow.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { contradictionTokens } from "../src/contradiction.ts";
import { runContradictionVectors, type ContradictionVectorFile } from "../src/contradictionVectors.ts";
import { askAssistant } from "../src/flow.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/contradiction_vectors.json", import.meta.url));
const file: ContradictionVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the contradiction vector file is the expected format", () => {
  assert.equal(file.format, "archways contradiction vectors v1");
  assert.equal(file.rule, "contradiction_v1");
  assert.equal(file.cases.length, 20);
});

test("runContradictionVectors reports every vector passing", () => {
  const report = runContradictionVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 20);
});

test("apostrophes join only between word characters", () => {
  assert.deepEqual(contradictionTokens("can't can’t 'quoted' end'"), ["can't", "can't", "quoted", "end"]);
});

const RESULT = {
  id: "29",
  title: "Dress Code Advisory",
  excerpt: "Crop tops are strictly prohibited inside the campus.",
  office: "Office for Student Affairs",
  priority: "NORMAL",
  year_level: null,
  posted_at: "2026-11-06T17:31:05+08:00",
};

function ask(reply: string, contradiction?: "contradiction_v1" | null) {
  return askAssistant("Can I wear a crop top on a wash day?", {
    nowMs: () => Date.parse("2026-11-17T10:00:00+08:00"),
    complete: (call) =>
      Promise.resolve({ text: call.kind === "query" ? '{"query": "crop top", "days": 30}' : reply }),
    search: () => Promise.resolve([RESULT]),
    countTokens: () => Promise.resolve(150),
    ...(contradiction === undefined ? {} : { contradiction: contradiction }),
  });
}

test("askAssistant with contradiction_v1 blocks with the list and the code", async () => {
  const result = await ask("Yes, you can wear a crop top.", "contradiction_v1");
  assert.equal(result.path, "guard_fired");
  assert.ok(result.codes.indexOf("contradiction") !== -1);
  assert.ok(result.text.startsWith("These announcements may help:"));
});

test("askAssistant default is off; a correct no passes with the rule on", async () => {
  assert.equal((await ask("Yes, you can wear a crop top.")).path, "answer");
  assert.equal((await ask("No, crop tops are not allowed.", "contradiction_v1")).path, "answer");
});
