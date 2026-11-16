// The frozen FINAL configuration (archways_assistant/frozen.py) is the phone
// default: makeFeedSearch() searches with rank_v1 + and_v4 and the first-500
// excerpt, without retry; askAssistant() applies strip_nf_v1.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { makeFeedSearch, type FeedIndex } from "../src/feedIndex.ts";
import { askAssistant } from "../src/flow.ts";
import {
  ANSWER_PROMPT_FILE,
  NOT_FOUND_MESSAGE,
  PHONE_EXCERPT,
  PHONE_MATCHER,
  PHONE_RANK,
  PHONE_RETRY,
  PHONE_STRIP_NF,
} from "../src/generated.ts";
import type { VectorFile } from "../src/vectors.ts";

const path = fileURLToPath(new URL("../../../../tests/vectors/assistant_vectors.json", import.meta.url));
const file: VectorFile = JSON.parse(readFileSync(path, "utf8"));

test("the generated phone defaults are the frozen FINAL set", () => {
  assert.equal(PHONE_RANK, "rank_v1");
  assert.equal(PHONE_MATCHER, "and_v4");
  assert.equal(PHONE_RETRY, null);
  assert.equal(PHONE_EXCERPT, null);
  assert.equal(PHONE_STRIP_NF, "strip_nf_v1");
  assert.equal(ANSWER_PROMPT_FILE, "prompts/e2e_answer_v1.txt");
});

function spyIndex(seen: unknown[]): FeedIndex {
  return {
    ensure: async () => ({}) as never,
    rebuild: async () => ({}) as never,
    clear: () => undefined,
    size: () => 0,
    search: (_args: unknown, _now?: number, score?: unknown, matcher?: unknown, excerpt?: unknown) => {
      seen.push({ ranked: score !== undefined, matcher: matcher, window: excerpt !== undefined });
      return [];
    },
    searchRetry: () => {
      seen.push("retry");
      return { results: [], retried: false };
    },
  } as unknown as FeedIndex;
}

test("makeFeedSearch defaults: rank_v1 with and_v4, no window, no retry", async () => {
  const seen: unknown[] = [];
  const search = makeFeedSearch(spyIndex(seen), () => 0);
  await assert.rejects(search({ query: "x" }), /rank needs the question/);
  await search({ query: "x" }, { question: "x?" });
  assert.deepEqual(seen, [{ ranked: true, matcher: "and_v4", window: false }]);
  // The UAT baseline is still reachable explicitly.
  const baseline = makeFeedSearch(spyIndex(seen), () => 0, null, null, undefined, "and_v3", null);
  await baseline({ query: "x" });
  assert.deepEqual(seen[1], { ranked: false, matcher: "and_v3", window: false });
});

async function ask(id: string, stripNf?: "strip_nf_v1" | null) {
  const v = file.flow.find((f) => f.id === id);
  if (!v) throw new Error("no vector " + id);
  return askAssistant(v.question, {
    nowMs: () => v.now_ms,
    complete: (call) => Promise.resolve({ text: (call.kind === "query" ? v.query_reply : v.answer_reply) as string }),
    search: () => Promise.resolve(v.search_reply),
    countTokens: () => Promise.resolve(v.case_tokens as number),
    ...(stripNf === undefined ? {} : { stripNf: stripNf }),
  });
}

test("askAssistant default applies strip_nf_v1; null is the UAT flow", async () => {
  const on = file.flow.find((f) => f.id === "strip-nf-answer-then-sentence");
  const off = file.flow.find((f) => f.id === "strip-nf-off-answer-then-sentence");
  assert.ok(on && off && on.answer_reply === off.answer_reply);
  const byDefault = await ask("strip-nf-off-answer-then-sentence");
  assert.equal(byDefault.path, "answer");
  assert.equal(byDefault.text, on.expected.text);
  assert.equal(byDefault.text.indexOf(NOT_FOUND_MESSAGE), -1);
  const explicitOff = await ask("strip-nf-off-answer-then-sentence", null);
  assert.equal(explicitOff.text, off.expected.text);
});
