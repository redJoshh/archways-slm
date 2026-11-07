/**
 * One feed detail -> one index row (ADR 0006): a port of
 * src/archways_assistant/feedindex.py feed_row() and parse_published_at().
 * Pure; the fetching and refreshing is in feedIndex.ts.
 *
 * - id: an integral JSON number, as decimal digits
 * - title: cut to TITLE_MAX_CHARS code points
 * - body: plainText() (the contract's rule); the excerpt is its first
 *   EXCERPT_CHARS code points, and matching uses the whole plain text
 * - office: officeName, priority: priority ("" if missing or not a string)
 * - year_level: null for every item (the feed already filtered by year)
 * - posted_at: publishedAt converted to Manila, "YYYY-MM-DDTHH:MM:SS+08:00",
 *   truncated to seconds. Without an offset, +08:00 is assumed and the row
 *   is flagged offsetAdded: that assumes the server clock is Manila time.
 * An item without a usable publishedAt (or id, title or body) is skipped.
 */

import { isIntegral } from "./contract.ts";
import { cutCodePoints, plainText } from "./plaintext.ts";
import type { IndexRow } from "./search.ts";
import { EXCERPT_CHARS, TITLE_MAX_CHARS, YEAR_MAX, YEAR_MIN } from "./searchData.ts";

const PUBLISHED_AT =
  /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})?$/;
const MANILA_MS = 8 * 3600000;

export interface PublishedAt {
  /** The instant in ms since the epoch, truncated to whole seconds. */
  ms: number;
  /** "YYYY-MM-DDTHH:MM:SS+08:00" */
  manila: string;
  offsetAdded: boolean;
}

function padNumber(value: number, width: number): string {
  let text = String(value);
  while (text.length < width) text = "0" + text;
  return text;
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0 ? 29 : 28;
  return [4, 6, 9, 11].indexOf(month) !== -1 ? 30 : 31;
}

export function parsePublishedAt(value: unknown): PublishedAt | null {
  if (typeof value !== "string") return null;
  const m = PUBLISHED_AT.exec(value);
  if (m === null) return null;
  const [year, month, day, hour, minute, second] = [1, 2, 3, 4, 5, 6].map((i) => parseInt(m[i], 10));
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  const offsetText = m[8];
  const offsetAdded = offsetText === undefined;
  let offsetMinutes = 8 * 60;
  if (!offsetAdded && offsetText !== "Z") {
    const oh = parseInt(offsetText.slice(1, 3), 10);
    const om = parseInt(offsetText.slice(4, 6), 10);
    if (oh > 23 || om > 59) return null;
    offsetMinutes = (offsetText.charAt(0) === "-" ? -1 : 1) * (oh * 60 + om);
  } else if (offsetText === "Z") offsetMinutes = 0;
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, 0);
  const ms = date.getTime() - offsetMinutes * 60000;
  const local = new Date(ms + MANILA_MS);
  const y = local.getUTCFullYear();
  if (y < YEAR_MIN || y > YEAR_MAX) return null;
  const manila =
    padNumber(y, 4) + "-" + padNumber(local.getUTCMonth() + 1, 2) + "-" + padNumber(local.getUTCDate(), 2) + "T" +
    padNumber(local.getUTCHours(), 2) + ":" + padNumber(local.getUTCMinutes(), 2) + ":" + padNumber(local.getUTCSeconds(), 2) +
    "+08:00";
  return { ms: ms, manila: manila, offsetAdded: offsetAdded };
}

function textField(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** The index row for one feed detail, or null to skip it. */
export function feedRow(detail: unknown): { row: IndexRow; offsetAdded: boolean } | null {
  if (typeof detail !== "object" || detail === null || Array.isArray(detail)) return null;
  const d = detail as { [key: string]: unknown };
  if (!isIntegral(d.id) || typeof d.title !== "string" || typeof d.body !== "string") return null;
  const published = parsePublishedAt(d.publishedAt);
  if (published === null) return null;
  const title = cutCodePoints(d.title, TITLE_MAX_CHARS);
  const body = plainText(d.body);
  return {
    row: {
      announcement: {
        id: String(d.id),
        title: title,
        excerpt: cutCodePoints(body, EXCERPT_CHARS),
        office: textField(d.officeName),
        priority: textField(d.priority),
        year_level: null,
        posted_at: published.manila,
      },
      title: title.toLowerCase(),
      body: body.toLowerCase(),
      publishedMs: published.ms,
    },
    offsetAdded: published.offsetAdded,
  };
}
