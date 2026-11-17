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

function fakeApi(
  items: Item[],
  options: {
    failPage?: number;
    failDetail?: number;
    status?: number;
    gone?: number[];
    // requested id -> the id the detail answers with (backend a823988 forwarding)
    forward?: { [id: number]: number };
    // add the backend's trailing "bookmarked" and an unknown field to every DTO
    extra?: boolean;
  } = {},
) {
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
        ...(options.extra ? { bookmarked: true, someFutureField: { nested: [1] } } : {}),
      }));
      return { content: content, page: p, size: size, hasNext: (p + 1) * size < items.length };
    }
    const detail = /^\/announcements\/(\d+)$/.exec(path);
    if (detail) {
      const requested = Number(detail[1]);
      const id = options.forward && options.forward[requested] !== undefined ? options.forward[requested] : requested;
      const found = items.find((i) => i.id === id) || (options.forward && options.forward[requested] !== undefined ? forwardedItems[id] : undefined);
      if (options.failDetail === id) throw new HttpError(options.status || 500);
      if (!found || (options.gone || []).indexOf(id) !== -1) throw new HttpError(404);
      return {
        id: found.id, title: found.title, body: found.body, priority: "NORMAL", officeName: "Office",
        publishedAt: found.publishedAt, version: 1, attachments: [],
        ...(options.extra ? { bookmarked: false, someFutureField: null } : {}),
      };
    }
    throw new Error("unexpected path " + path);
  };
  return { fetchJson, requests, maxActive: () => maxActive };
}

// Revisions the detail endpoint can forward to although the feed page
// doesn't list them (an edit approved between the list and the detail).
const forwardedItems: { [id: number]: Item } = {
  90: item(90, "Edited notice (revision 2)", "<p>Revised body</p>", "2026-11-07T09:00:00+08:00"),
  91: item(91, "Edited notice (revision 3)", "<p>Third body</p>", "2026-11-07T10:00:00+08:00"),
};

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

test("a forwarded detail is stored under the RESPONSE id, the requested id dropped, and counted", async () => {
  // Item 2 was edited after the list: GET /announcements/2 answers revision 90.
  const items = [item(1, "Kept"), item(2, "Old revision"), item(3, "Also kept")];
  const logs: IndexReport[] = [];
  const index = createFeedIndex(fakeApi(items, { forward: { 2: 90 } }).fetchJson, {
    clockMs: () => NOW,
    log: (r) => logs.push(r),
  });
  const report = await index.ensure();
  assert.equal(report.forwarded, 1);
  assert.equal(report.skipped, 0);
  assert.equal(report.detailsFetched, 3);
  assert.equal(report.rows, 3);
  assert.equal(logs[0].forwarded, 1);
  const ids = index
    .search({ query: "notice kept", days: 30 }, NOW)
    .concat(index.search({ query: "edited", days: 30 }, NOW), index.search({ query: "kept", days: 30 }, NOW))
    .map((a) => a.id);
  assert.ok(ids.indexOf("90") !== -1, "the revision is searchable under its own id");
  assert.equal(index.search({ query: "old", days: 30 }, NOW).length, 0, "the requested id is gone");
});

test("forwarded details are deduped: one row per response id", async () => {
  // 2 and 4 both forward to 91, and 91 is listed itself.
  const items = [item(1, "Kept"), item(2, "Old A"), item(4, "Old B"), item(91, "Edited notice (revision 3)")];
  const index = createFeedIndex(fakeApi(items, { forward: { 2: 91, 4: 91 } }).fetchJson, { clockMs: () => NOW });
  const report = await index.ensure();
  assert.equal(report.forwarded, 2);
  assert.equal(report.rows, 2);
  assert.equal(index.size(), 2);
  assert.deepEqual(
    index.search({ query: "edited", days: 30 }, NOW).map((a) => a.id),
    ["91"],
  );
});

test("a forwarded revision not listed in the feed is fetched again on the next refresh", async () => {
  let now = NOW;
  const items = [item(1, "Kept"), item(2, "Old revision")];
  const api = fakeApi(items, { forward: { 2: 90 } });
  const index = createFeedIndex(api.fetchJson, { clockMs: () => now });
  await index.ensure();
  // The feed now lists the revision instead of the archived id.
  items.splice(1, 1, forwardedItems[90]);
  now += 10 * 60000;
  const before = api.requests.length;
  const refresh = await index.ensure();
  assert.equal(refresh.kind, "refresh");
  assert.deepEqual(api.requests.slice(before).filter((p) => p.indexOf("?") === -1), ["/announcements/90"]);
  assert.equal(refresh.forwarded, 0);
  assert.equal(index.size(), 2);
});

test("unknown extra fields (bookmarked, future fields) are ignored in pages and details", async () => {
  const items = many(3);
  const plain = createFeedIndex(fakeApi(items).fetchJson, { clockMs: () => NOW });
  const extra = createFeedIndex(fakeApi(items, { extra: true }).fetchJson, { clockMs: () => NOW });
  const a = await plain.ensure();
  const b = await extra.ensure();
  assert.equal(b.rows, 3);
  assert.equal(b.skipped, 0);
  assert.deepEqual({ ...a, fetchMs: 0, indexMs: 0 }, { ...b, fetchMs: 0, indexMs: 0 });
  assert.deepEqual(
    extra.search({ query: "notice", days: 30 }, NOW),
    plain.search({ query: "notice", days: 30 }, NOW),
  );
});
