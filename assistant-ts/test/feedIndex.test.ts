// The in-memory feed index (ADR 0006) against a fake API.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createFeedIndex, HttpError, makeFeedSearch, type IndexReport } from "../src/feedIndex.ts";
import { askAssistant } from "../src/flow.ts";

const NOW = Date.parse("2026-11-07T16:00:00+08:00");

interface Item {
  id: number;
  title: string;
  body: string;
  publishedAt: string | null;
}

function item(id: number, title: string, body = "<p>Body " + id + "</p>", publishedAt: string | null = "2026-11-06T10:00:00+08:00"): Item {
  return { id: id, title: title, body: body, publishedAt: publishedAt };
}

function fakeApi(items: Item[], options: { failPage?: number; failDetail?: number; status?: number; gone?: number[] } = {}) {
  const requests: string[] = [];
  let active = 0;
  let maxActive = 0;
  const fetchJson = async (path: string): Promise<unknown> => {
    requests.push(path);
    active++;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 1));
    active--;
    const page = /^\/announcements\?page=(\d+)&size=(\d+)$/.exec(path);
    if (page) {
      const p = Number(page[1]);
      const size = Number(page[2]);
      if (options.failPage === p) throw new HttpError(options.status || 500);
      const content = items.slice(p * size, (p + 1) * size).map((i) => ({
        id: i.id, title: i.title, excerpt: i.body.slice(0, 160), priority: "NORMAL",
        officeName: "Office", publishedAt: i.publishedAt, pinned: false, read: false,
      }));
      return { content: content, page: p, size: size, hasNext: (p + 1) * size < items.length };
    }
    const detail = /^\/announcements\/(\d+)$/.exec(path);
    if (detail) {
      const id = Number(detail[1]);
      const found = items.find((i) => i.id === id);
      if (options.failDetail === id) throw new HttpError(options.status || 500);
      if (!found || (options.gone || []).indexOf(id) !== -1) throw new HttpError(404);
      return {
        id: found.id, title: found.title, body: found.body, priority: "NORMAL", officeName: "Office",
        publishedAt: found.publishedAt, version: 1, attachments: [],
      };
    }
    throw new Error("unexpected path " + path);
  };
  return { fetchJson, requests, maxActive: () => maxActive };
}

function many(n: number): Item[] {
  const out: Item[] = [];
  for (let i = 1; i <= n; i++) out.push(item(i, "Notice " + i));
  return out;
}

test("a full build reads every page and every detail, at most 4 at a time, and never the read POST", async () => {
  const api = fakeApi(many(107));
  const logs: IndexReport[] = [];
  const index = createFeedIndex(api.fetchJson, { clockMs: () => NOW, log: (r) => logs.push(r) });
  const report = await index.ensure();
  assert.equal(report.kind, "full");
  assert.equal(report.pages, 3);
  assert.equal(report.items, 107);
  assert.equal(report.detailsFetched, 107);
  assert.equal(report.rows, 107);
  assert.equal(index.size(), 107);
  assert.ok(api.maxActive() <= 4, "parallelism " + api.maxActive());
  assert.ok(api.requests.every((p) => /^\/announcements(\?page=\d+&size=50|\/\d+)$/.test(p)));
  assert.ok(api.requests.every((p) => p.indexOf("read") === -1));
  assert.equal(logs.length, 1);
  for (const [key, value] of Object.entries(logs[0])) {
    assert.ok(typeof value !== "string" || key === "kind", key + " must not be text");
  }
});

test("skips 404 details, unusable publishedAt and counts added offsets", async () => {
  const items = [
    item(1, "Good"),
    item(2, "No date", "<p>x</p>", null),
    item(3, "Gone"),
    item(4, "Naive", "<p>y</p>", "2026-11-06T10:00:00"),
  ];
  const index = createFeedIndex(fakeApi(items, { gone: [3] }).fetchJson, { clockMs: () => NOW });
  const report = await index.ensure();
  assert.equal(report.skipped, 2);
  assert.equal(report.offsetAdded, 1);
  assert.equal(index.size(), 2);
});

test("ensure: nothing within 10 minutes, a refresh after 10, a full build after 60", async () => {
  let now = NOW;
  const items = many(5);
  const api = fakeApi(items);
  const index = createFeedIndex(api.fetchJson, { clockMs: () => now });
  await index.ensure();
  now += 9 * 60000;
  assert.equal((await index.ensure()).kind, "none");

  // A changed title, a new id and a removed id.
  items[0] = item(1, "Notice 1 (edited)");
  items.push(item(6, "Notice 6"));
  items.splice(1, 1); // id 2 removed
  now += 60000;
  const before = api.requests.length;
  const refresh = await index.ensure();
  assert.equal(refresh.kind, "refresh");
  assert.equal(refresh.detailsFetched, 2);
  assert.equal(refresh.removed, 1);
  assert.deepEqual(
    api.requests.slice(before).filter((p) => /\/\d+$/.test(p)).sort(),
    ["/announcements/1", "/announcements/6"],
  );
  assert.equal(index.size(), 5);
  assert.equal(index.search({ query: "edited" }, NOW)[0].id, "1");

  now += 50 * 60000;
  assert.equal((await index.ensure()).kind, "full");
});

test("a 401 rejects and leaves the previous index as it was", async () => {
  let now = NOW;
  const good = fakeApi(many(3));
  let fetchJson = good.fetchJson;
  const index = createFeedIndex((p) => fetchJson(p), { clockMs: () => now });
  await index.ensure();
  fetchJson = fakeApi(many(3), { failPage: 0, status: 401 }).fetchJson;
  now += 11 * 60000;
  await assert.rejects(index.ensure(), (error: unknown) => error instanceof HttpError && error.status === 401);
  assert.equal(index.size(), 3);
});

test("a 401 on a detail rejects too (only 404 details are skipped)", async () => {
  const index = createFeedIndex(fakeApi(many(5), { failDetail: 3, status: 401 }).fetchJson, { clockMs: () => NOW });
  await assert.rejects(index.ensure(), (error: unknown) => error instanceof HttpError && error.status === 401);
  assert.equal(index.size(), 0);
});

test("clear() empties the index and discards a build still running", async () => {
  const index = createFeedIndex(fakeApi(many(20)).fetchJson, { clockMs: () => NOW });
  const running = index.ensure();
  index.clear();
  await running;
  assert.equal(index.size(), 0);
  assert.equal((await index.ensure()).kind, "full");
  assert.equal(index.size(), 20);
  index.clear();
  assert.equal(index.size(), 0);
});

test("concurrent ensure() calls share one build", async () => {
  const api = fakeApi(many(3));
  const index = createFeedIndex(api.fetchJson, { clockMs: () => NOW });
  const [a, b] = await Promise.all([index.ensure(), index.ensure()]);
  assert.equal(a, b);
  assert.equal(api.requests.filter((p) => p.indexOf("page=") !== -1).length, 1);
});

test("askAssistant searches the feed index (and_v3, plain text, newest first)", async () => {
  const items = [
    item(10, "Drop Form Deadline", "<p>Submit the drop <b>form</b> by Friday.</p>", "2026-11-05T09:00:00+08:00"),
    item(11, "Information Desk", "<p>Visit the information desk.</p>", "2026-11-06T09:00:00+08:00"),
    item(12, "Leave Request", "<p>Fill out the leave form.</p>", "2026-11-06T10:00:00+08:00"),
  ];
  const index = createFeedIndex(fakeApi(items).fetchJson, { clockMs: () => NOW });
  const result = await askAssistant("Where are the forms?", {
    nowMs: () => NOW,
    complete: (call) =>
      Promise.resolve({ text: call.kind === "query" ? '{"query": "forms", "days": 30}' : "Use the drop form." }),
    search: makeFeedSearch(index, () => NOW),
    countTokens: () => Promise.resolve(150),
  });
  assert.deepEqual(
    (result.trace.results || []).map((r) => r.id),
    ["12", "10"],
  );
  assert.equal(result.trace.results![0].posted_at, "2026-11-06T10:00:00+08:00");
  assert.equal(result.trace.results![1].excerpt, "Submit the drop form by Friday.");
  assert.equal(result.trace.results![0].year_level, null);
});
