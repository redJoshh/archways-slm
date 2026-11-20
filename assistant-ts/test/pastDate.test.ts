// past_date_v1 (v2 fix (c)) against the hand-written
// tests/vectors/past_date_vectors.json, and in the flow.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { askAssistant } from "../src/flow.ts";
import { PAST_DATE_NOTE } from "../src/pastDate.ts";
import { runPastDateVectors, type PastDateVectorFile } from "../src/pastDateVectors.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/past_date_vectors.json", import.meta.url));
const file: PastDateVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the past_date vector file is the expected format", () => {
  assert.equal(file.format, "archways past_date vectors v1");
  assert.equal(file.rule, "past_date_v1");
  assert.equal(file.note, PAST_DATE_NOTE);
  assert.equal(file.cases.length, 22);
});

test("runPastDateVectors: every vector, with claims and guard unchanged", () => {
  const report = runPastDateVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 22);
});

const RESULT = {
  id: "10",
  title: "Misa de Apertura",
  excerpt: "The Mass is on August 7, 2026.",
  office: "Test Office",
  priority: "NORMAL",
  year_level: null,
  posted_at: "2026-11-06T09:00:00+08:00",
};

function ask(reply: string, pastDate?: "past_date_v1" | null) {
  return askAssistant("When is the Misa de Apertura?", {
    nowMs: () => Date.parse("2026-11-10T10:00:00+08:00"),
    complete: (call) =>
      Promise.resolve({ text: call.kind === "query" ? '{"query": "Misa de Apertura", "days": 30}' : reply }),
    search: () => Promise.resolve([RESULT]),
    countTokens: () => Promise.resolve(150),
    // The answer path: extract_v1 (on by default) would quote instead.
    extract: null,
    ...(pastDate === undefined ? {} : { pastDate: pastDate }),
  });
}

test("askAssistant with past_date_v1 notes the answer, never the list", async () => {
  const result = await ask("It is held on August 7, 2026.", "past_date_v1");
  assert.equal(result.path, "answer");
  assert.ok(result.codes.indexOf("past_date") !== -1);
  const at = result.text.indexOf("\n\nThese announcements may help:");
  assert.ok(at > 0);
  assert.ok(result.text.slice(0, at).endsWith("August 7, 2026 (already passed)."));
  assert.equal(result.text.slice(at).indexOf(PAST_DATE_NOTE), -1);
});

test("askAssistant default is on (FINAL_V2), null is off; a future date gets no note", async () => {
  const on = await ask("It is held on August 7, 2026.");
  assert.ok(on.text.indexOf(PAST_DATE_NOTE) !== -1);
  const off = await ask("It is held on August 7, 2026.", null);
  assert.equal(off.text.indexOf(PAST_DATE_NOTE), -1);
  const future = await ask("It is on January 15, 2027.", "past_date_v1");
  assert.equal(future.text.indexOf(PAST_DATE_NOTE), -1);
  assert.equal(future.codes.indexOf("past_date"), -1);
});
