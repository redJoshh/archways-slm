// The frozen lists are exactly these values (the Python test checks its own
// copy the same way), plus a few direct checks of the date parser.
import assert from "node:assert/strict";
import { test } from "node:test";

import { fallback, guard, postedDate } from "../src/guard.ts";
import {
  FALLBACK_HEADER,
  GUARD_SPACES,
  LAST_RESORT_MESSAGE,
  NON_ASCII_DIGIT_RANGES,
} from "../src/spec.ts";

test("GUARD_SPACES is the frozen list", () => {
  const expected = [0x85, 0xa0, 0x1680];
  for (let cp = 0x2000; cp <= 0x200a; cp++) expected.push(cp);
  expected.push(0x2028, 0x2029, 0x202f, 0x205f, 0x3000);
  assert.deepEqual([...GUARD_SPACES], expected);
});

test("NON_ASCII_DIGIT_RANGES are 63 runs of ten (one of fifty)", () => {
  assert.equal(NON_ASCII_DIGIT_RANGES.length, 63);
  assert.deepEqual(NON_ASCII_DIGIT_RANGES[0], [0x0660, 0x0669]);
  assert.deepEqual(NON_ASCII_DIGIT_RANGES[62], [0x1fbf0, 0x1fbf9]);
  const sizes = NON_ASCII_DIGIT_RANGES.map(([a, b]) => b - a + 1);
  assert.equal(sizes.filter((n) => n === 10).length, 62);
  assert.ok(sizes.includes(50)); // U+1D7CE-U+1D7FF, mathematical digits
});

test("messages are the frozen text", () => {
  assert.equal(FALLBACK_HEADER, "I found these announcements:");
  assert.equal(
    LAST_RESORT_MESSAGE,
    "Sorry, I can't show an answer right now. Please check the Announcements page for the official details.",
  );
});

test("postedDate reads the contract format and nothing else", () => {
  assert.deepEqual(postedDate("2028-02-29T00:00:00Z"), { year: 2028, month: 2, day: 29 });
  assert.deepEqual(postedDate("2026-10-29t23:59:59.1234567-05:30"), {
    year: 2026,
    month: 10,
    day: 29,
  });
  for (const bad of ["2026-11-03", "2026-02-29T00:00:00Z", "2026-11-03T08:00:60Z", "2026-11-03T08:00:00+08:00\n"]) {
    assert.throws(() => postedDate(bad), bad);
  }
});

test("a fired guard with an unreadable posted_at gives the last resort", () => {
  const row = {
    id: "r-1",
    title: "T",
    excerpt: "Due November 13.",
    office: "O",
    priority: "HIGH",
    year_level: null,
    posted_at: "2026-11-03",
  };
  assert.throws(() => fallback([row]));
  assert.equal(guard("Due November 6.", [row], "When?", []).text, LAST_RESORT_MESSAGE);
  assert.equal(guard("Due November 13.", [row], "When?", []).text, "Due November 13.");
});
