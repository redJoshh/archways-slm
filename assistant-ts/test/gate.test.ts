// gate_v1's decision (accuracy-phase.md (d)) against the hand-written tests/vectors/gate_vectors.json.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { runGateVectors, type GateVectorFile } from "../src/gateVectors.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/gate_vectors.json", import.meta.url));
const file: GateVectorFile = JSON.parse(readFileSync(path, "utf8"));

test("runGateVectors reports every gate vector passing", () => {
  assert.equal(file.format, "archways gate vectors v1");
  const report = runGateVectors(file);
  assert.deepEqual(report.failures, []);
  assert.equal(report.total, 12);
});
