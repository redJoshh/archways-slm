/**
 * The in-memory feed index (ADR 0006): what the phone searches.
 *
 * The app passes fetchJson(path), which GETs `${apiBase}${path}` with the
 * student's Bearer token and resolves to the parsed JSON, or rejects with an
 * HttpError carrying the status. This module never calls the read POST, and
 * never writes anything to disk.
 *
 * - Full build: every feed page (GET /announcements?page=P&size=50, until
 *   hasNext is false), then every detail (GET /announcements/{id}), at most
 *   `parallel` (4) at a time; each detail becomes a row with feedRow().
 * - ensure(), on opening the assistant and before each search:
 *   - no index, or the last full build is fullMs (60 min) old or more: a
 *     full build
 *   - otherwise, if the last build or refresh is refreshMs (10 min) old or
 *     more: a refresh. It re-reads the feed pages only, fetches the details
 *     of new ids and of ids whose summary changed (title, excerpt,
 *     publishedAt, priority or officeName), and drops ids no longer in the
 *     feed. Approved edits are new rows (the old one is archived), so a
 *     changed id set catches them. An in-place edit deeper in the body is
 *     invisible to the summaries; the hourly full build is the backstop.
 *   - otherwise nothing.
 * - clear(): on sign-out and on a 401. A build still running when clear()
 *   is called is discarded when it finishes.
 * - A detail that answers 404 (removed between the list and the detail) is
 *   skipped and counted; any other error (a 401 included) rejects, and the
 *   previous index stays as it was.
 * - Every build or refresh is reported to options.log: numbers only (pages,
 *   items, details fetched, removed, skipped, offsets added, fetch ms,
 *   index ms), never text.
 */

import type { Announcement } from "./render.ts";
import { feedRow } from "./feed.ts";
import { searchRows, type IndexRow } from "./search.ts";

export class HttpError extends Error {
  status: number;
  constructor(status: number, message?: string) {
    super(message || "HTTP " + status);
    this.status = status;
  }
}

export type FetchJson = (path: string) => Promise<unknown>;

export interface FeedIndexOptions {
  pageSize?: number;
  parallel?: number;
  refreshMs?: number;
  fullMs?: number;
  /** A guard against a feed that never ends. */
  maxPages?: number;
  clockMs?: () => number;
  log?: (report: IndexReport) => void;
}

export interface IndexReport {
  kind: "full" | "refresh" | "none";
  pages: number;
  /** Items listed in the feed pages. */
  items: number;
  detailsFetched: number;
  removed: number;
  /** Details that were 404 or could not be mapped (feedRow returned null). */
  skipped: number;
  /** Rows whose publishedAt had no offset (+08:00 assumed). */
  offsetAdded: number;
  /** Rows in the index after this build. */
  rows: number;
  /** Time spent waiting for the network (pages and details). */
  fetchMs: number;
  /** Time spent mapping details to rows (plain text and so on). */
  indexMs: number;
  /** True if maxPages stopped the listing before hasNext was false. */
  truncated: boolean;
}

interface Entry {
  row: IndexRow;
  key: string;
}

export interface FeedIndex {
  ensure: () => Promise<IndexReport>;
  rebuild: () => Promise<IndexReport>;
  clear: () => void;
  search: (args: unknown, nowMs?: number) => Announcement[];
  size: () => number;
}

function summaryKey(item: { [key: string]: unknown }): string {
  return JSON.stringify([item.title, item.excerpt, item.publishedAt, item.priority, item.officeName]);
}

function isIntegralId(value: unknown): value is number {
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value;
}

export function createFeedIndex(fetchJson: FetchJson, options: FeedIndexOptions = {}): FeedIndex {
  const pageSize = options.pageSize || 50;
  const parallel = options.parallel || 4;
  const refreshMs = options.refreshMs === undefined ? 10 * 60000 : options.refreshMs;
  const fullMs = options.fullMs === undefined ? 60 * 60000 : options.fullMs;
  const maxPages = options.maxPages || 200;
  const clock = options.clockMs || Date.now;

  let entries: Map<string, Entry> | null = null;
  let builtAt = 0;
  let refreshedAt = 0;
  let generation = 0;
  let inFlight: Promise<IndexReport> | null = null;

  async function listFeed(report: IndexReport): Promise<Map<string, string>> {
    const listed = new Map<string, string>();
    for (let page = 0; ; page++) {
      if (page >= maxPages) {
        report.truncated = true;
        break;
      }
      const started = clock();
      const body = (await fetchJson("/announcements?page=" + page + "&size=" + pageSize)) as {
        content?: unknown;
        hasNext?: unknown;
      };
      report.fetchMs += clock() - started;
      report.pages++;
      const content = body && Array.isArray(body.content) ? body.content : [];
      for (const item of content) {
        if (typeof item !== "object" || item === null) continue;
        const summary = item as { [key: string]: unknown };
        if (!isIntegralId(summary.id)) continue;
        listed.set(String(summary.id), summaryKey(summary));
      }
      if (!body || body.hasNext !== true) break;
    }
    report.items = listed.size;
    return listed;
  }

  async function fetchDetails(ids: string[], report: IndexReport, into: Map<string, Entry>, keys: Map<string, string>) {
    let next = 0;
    async function worker() {
      while (next < ids.length) {
        const id = ids[next++];
        const started = clock();
        let detail: unknown;
        try {
          detail = await fetchJson("/announcements/" + id);
        } catch (error) {
          report.fetchMs += clock() - started;
          if (error instanceof HttpError && error.status === 404) {
            report.skipped++;
            into.delete(id);
            continue;
          }
          throw error;
        }
        report.fetchMs += clock() - started;
        report.detailsFetched++;
        const mapStarted = clock();
        const mapped = feedRow(detail);
        report.indexMs += clock() - mapStarted;
        if (mapped === null || mapped.row.announcement.id !== id) {
          report.skipped++;
          into.delete(id);
          continue;
        }
        if (mapped.offsetAdded) report.offsetAdded++;
        into.set(id, { row: mapped.row, key: keys.get(id) as string });
      }
    }
    const workers: Promise<void>[] = [];
    for (let i = 0; i < Math.min(parallel, ids.length); i++) workers.push(worker());
    await Promise.all(workers);
  }

  function emptyReport(kind: IndexReport["kind"]): IndexReport {
    return {
      kind: kind, pages: 0, items: 0, detailsFetched: 0, removed: 0, skipped: 0,
      offsetAdded: 0, rows: entries ? entries.size : 0, fetchMs: 0, indexMs: 0, truncated: false,
    };
  }

  async function run(kind: "full" | "refresh"): Promise<IndexReport> {
    const myGeneration = generation;
    const report = emptyReport(kind);
    const listed = await listFeed(report);
    const next = new Map<string, Entry>();
    let wanted: string[];
    if (kind === "full" || entries === null) {
      wanted = Array.from(listed.keys());
    } else {
      wanted = [];
      listed.forEach((key, id) => {
        const old = (entries as Map<string, Entry>).get(id);
        if (old && old.key === key) next.set(id, old);
        else wanted.push(id);
      });
      (entries as Map<string, Entry>).forEach((_entry, id) => {
        if (!listed.has(id)) report.removed++;
      });
    }
    await fetchDetails(wanted, report, next, listed);
    if (myGeneration !== generation) return emptyReport("none"); // cleared meanwhile
    entries = next;
    const now = clock();
    if (kind === "full") builtAt = now;
    refreshedAt = now;
    report.rows = next.size;
    if (options.log) {
      try {
        options.log(report);
      } catch (error) {
        // Logging never changes the index.
      }
    }
    return report;
  }

  function start(kind: "full" | "refresh"): Promise<IndexReport> {
    const promise = run(kind);
    inFlight = promise;
    const done = () => {
      if (inFlight === promise) inFlight = null;
    };
    promise.then(done, done);
    return promise;
  }

  return {
    ensure: () => {
      if (inFlight) return inFlight;
      const now = clock();
      if (entries === null || now - builtAt >= fullMs) return start("full");
      if (now - refreshedAt >= refreshMs) return start("refresh");
      return Promise.resolve(emptyReport("none"));
    },
    rebuild: () => (inFlight ? inFlight : start("full")),
    clear: () => {
      generation++;
      entries = null;
      builtAt = 0;
      refreshedAt = 0;
      inFlight = null;
    },
    search: (args: unknown, nowMs?: number) => {
      const rows: IndexRow[] = [];
      if (entries) entries.forEach((entry) => rows.push(entry.row));
      return searchRows(rows, args, nowMs === undefined ? clock() : nowMs);
    },
    size: () => (entries ? entries.size : 0),
  };
}

/**
 * AssistantDeps.search over the feed index: brings the index up to date
 * (ensure(): a refresh or a full build only when due), then searches it.
 * The refresh time counts in the question's elapsed time, so the budget
 * sees it.
 */
export function makeFeedSearch(index: FeedIndex, nowMs: () => number = Date.now) {
  return async (args: unknown): Promise<unknown> => {
    await index.ensure();
    return index.search(args, nowMs());
  };
}
