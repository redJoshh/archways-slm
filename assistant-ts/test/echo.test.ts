// echo_v1 (v2 fix (b)) against the hand-written tests/vectors/echo_vectors.json,
// and in the flow.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { runEchoVectors, type EchoVectorFile } from "../src/echoVectors.ts";
import { askAssistant } from "../src/flow.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/echo_vectors.json", import.meta.url));
const file: EchoVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the echo vector file is the expected format", () => {
  assert.equal(file.format, "archways echo vectors v1");
  assert.equal(file.rule, "echo_v1");
  assert.equal(file.cases.length, 14);
});

test("runEchoVectors reports every vector passing", () => {
  const report = runEchoVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 14);
});

const RESULT = {
  id: "56",
  title: "Campus Plastic Ban",
  excerpt: "The ban covers straws, stirrers and plastic bags. Crop tops are prohibited.",
  office: "Facilities Management Office",
  priority: "NORMAL",
  year_level: null,
  posted_at: "2026-11-07T15:31:47+08:00",
};

function ask(question: string, reply: string, rules: { echo?: "echo_v1" | null; contradiction?: "contradiction_v1" | null }) {
  return askAssistant(question, {
    nowMs: () => Date.parse("2026-11-17T10:00:00+08:00"),
    complete: (call) =>
      Promise.resolve({ text: call.kind === "query" ? '{"query": "plastic ban", "days": 30}' : reply }),
    search: () => Promise.resolve([RESULT]),
    countTokens: () => Promise.resolve(150),
    ...rules,
  });
}

test("askAssistant with echo_v1: answer_not_found, the list and the code", async () => {
  const q = "Which items are included in the campus ban on plastics?";
  const result = await ask(q, "The campus ban on plastics includes items.", { echo: "echo_v1" });
  assert.equal(result.path, "answer_not_found");
  assert.ok(result.codes.indexOf("echo") !== -1);
  assert.ok(result.text.startsWith("These announcements may help:"));
  // Default on (FINAL_V2); null is off.
  assert.equal((await ask(q, "The campus ban on plastics includes items.", {})).path, "answer_not_found");
  assert.equal((await ask(q, "The campus ban on plastics includes items.", { echo: null })).path, "answer");
  assert.equal((await ask(q, "It covers straws, stirrers and plastic bags.", { echo: "echo_v1" })).path, "answer");
});

test("contradiction runs before echo", async () => {
  const result = await ask("Can I wear a crop top?", "Yes.", { echo: "echo_v1", contradiction: "contradiction_v1" });
  assert.equal(result.path, "guard_fired");
  assert.ok(result.codes.indexOf("contradiction") !== -1);
});
