// strip_nf_v1 (accuracy-phase.md, fix (g)) against tests/vectors/strip_nf_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { answerReplyText, startQuestion } from "../src/flow.ts";
import { runStripNfVectors, type StripNfVectorFile } from "../src/stripNfVectors.ts";
import { NOT_FOUND_MESSAGE } from "../src/generated.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/strip_nf_vectors.json", import.meta.url));
const file: StripNfVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("runStripNfVectors reports every strip_nf vector passing", () => {
  assert.equal(file.format, "archways strip_nf vectors v1");
  assert.equal(file.not_found, NOT_FOUND_MESSAGE);
  const report = runStripNfVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 9);
});

test("off (the default) is the UAT rule", () => {
  for (const c of file.cases) {
    const trimmed = c.reply.replace(/^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$/g, "");
    const expected = trimmed === NOT_FOUND_MESSAGE ? null : trimmed;
    assert.equal(answerReplyText(c.reply), expected, c.name);
    assert.equal(answerReplyText(c.reply, null), expected, c.name);
  }
});

test("an unknown rule is refused", () => {
  assert.throws(() => answerReplyText("x", "strip_nf_v2" as never));
  assert.throws(() => startQuestion("When?", 0, null, { stripNf: "strip_nf_v2" as never }));
});
