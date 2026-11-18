// extract_v1 (v2 fix (d)) against the hand-written
// tests/vectors/extract_vectors.json, and in askAssistant.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { EXTRACT_LABEL } from "../src/extract.ts";
import { runExtractVectors, type ExtractVectorFile } from "../src/extractVectors.ts";
import { askAssistant } from "../src/flow.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/extract_vectors.json", import.meta.url));
const file: ExtractVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the extract vector file is the expected format", () => {
  assert.equal(file.format, "archways extract vectors v1");
  assert.equal(file.rule, "extract_v1");
  assert.equal(file.label, EXTRACT_LABEL);
  assert.equal(file.cases.length, 30);
});

test("runExtractVectors: every step and the flow text", () => {
  const report = runExtractVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 30);
});

function ask(extract?: "extract_v1" | null) {
  const c = file.cases[0];
  const kinds: string[] = [];
  const result = askAssistant(c.question, {
    nowMs: () => Date.parse(c.now),
    complete: (call) => {
      kinds.push(call.kind);
      return Promise.resolve({ text: call.kind === "query" ? '{"query": "enrollment", "days": 30}' : "It is soon." });
    },
    search: () => Promise.resolve(c.results),
    countTokens: () => {
      kinds.push("count");
      return Promise.resolve(150);
    },
    ...(extract === undefined ? {} : { extract: extract }),
  });
  return result.then((r) => ({ result: r, kinds: kinds }));
}

test("askAssistant with extract_v1: the quote, no count and no answer call", async () => {
  const { result, kinds } = await ask("extract_v1");
  assert.equal(result.path, "extract");
  assert.deepEqual(kinds, ["query"]);
  assert.equal(
    result.text,
    "From the announcement below:\n" +
      "The deadline for enrollment is December 5, 2026.\n" +
      "\n" +
      "These announcements may help:\n" +
      "- Enrollment for the Second Term (posted November 6, 2026)\n" +
      "- Library Hours (posted November 6, 2026)",
  );
});

test("askAssistant default is off: the answer path with the model call", async () => {
  const { result, kinds } = await ask();
  assert.equal(result.path, "answer");
  assert.deepEqual(kinds, ["query", "count", "answer"]);
});
