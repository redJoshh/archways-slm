/**
 * past_date_v1 (v2 fix (c)) on the phone: a port of past_date.py.
 *
 * Rule: docs/plans/v2-improvements.md, "past_date_v1 rule, pre-registered"
 * (2026-11-18), checked by the hand-written tests/vectors/past_date_vectors.json.
 *
 * Spans are exactly guard-ts claimsAndRest's (the guard's and the scorer's
 * parse), sorted by start. A span's year: YYYY-MM-DD's first four digits,
 * else a four-digit run ending the span, else none (then the single year the
 * cited sources give for that month-day, or left). Two consecutive spans
 * joined only by to/until/through/thru or a dash form a range, judged by its
 * end, the note after the end. Past = strictly before now's Manila date;
 * impossible dates are left. Only the AI-answer text, never the list.
 */

import { claimsAndRest } from "../../guard-ts/src/guard.ts";
import { GUARD_SPACES } from "../../guard-ts/src/spec.ts";
import type { Announcement } from "./render.ts";

export type PastDateRule = "past_date_v1" | null;
export const PAST_DATE_CODE = "past_date";
export const PAST_DATE_NOTE = " (already passed)";
const PAST_RANGE_JOINERS: readonly string[] = ["to", "until", "through", "thru", "-", "–", "—"];
const PAST_ASCII_SPACE = " \t\n\r\f\v";
const PAST_MANILA_MS = 8 * 3600000;

interface PastSpan {
  start: number;
  end: number;
  month: number;
  day: number;
  year: number | null;
}

/** claimsAndRest's spans of text, sorted, each with its year (or null). */
export function pastSpans(text: string): PastSpan[] {
  const spans = claimsAndRest(text).spans.slice();
  spans.sort((a, b) => a.start - b.start);
  const out: PastSpan[] = [];
  for (const s of spans) {
    const segment = text.slice(s.start, s.end);
    let year: number | null = null;
    if (/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(segment)) year = parseInt(segment.slice(0, 4), 10);
    else {
      const digits = /[0-9]+$/.exec(segment);
      if (digits !== null && digits[0].length === 4) year = parseInt(digits[0], 10);
    }
    out.push({
      start: s.start,
      end: s.end,
      month: parseInt(s.date.slice(0, 2), 10),
      day: parseInt(s.date.slice(3, 5), 10),
      year: year,
    });
  }
  return out;
}

function pastResolveYear(month: number, day: number, sources: string[]): number | null {
  const years: number[] = [];
  for (const source of sources) {
    for (const s of pastSpans(source)) {
      if (s.month === month && s.day === day && s.year !== null && years.indexOf(s.year) === -1) years.push(s.year);
    }
  }
  return years.length === 1 ? years[0] : null;
}

/** Days since the epoch of a valid calendar date, or null if impossible. */
function pastDayNumber(year: number, month: number, day: number): number | null {
  const ms = Date.UTC(year, month - 1, day);
  const d = new Date(ms);
  if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) return null;
  return Math.floor(ms / 86400000);
}

function pastSpaced(text: string): string {
  let out = "";
  for (let i = 0; i < text.length; i++) {
    const unit = text.charCodeAt(i);
    out += GUARD_SPACES.indexOf(unit) !== -1 ? " " : text.charAt(i);
  }
  return out;
}

function pastTrimAscii(text: string): string {
  let a = 0;
  let b = text.length;
  while (a < b && PAST_ASCII_SPACE.indexOf(text.charAt(a)) !== -1) a++;
  while (b > a && PAST_ASCII_SPACE.indexOf(text.charAt(b - 1)) !== -1) b--;
  return text.slice(a, b);
}

/** text with PAST_DATE_NOTE after each past date (or past range end). */
export function annotatePastDates(text: string, sources: string[], nowMs: number): string {
  const manila = new Date(nowMs + PAST_MANILA_MS);
  const today = Math.floor(
    Date.UTC(manila.getUTCFullYear(), manila.getUTCMonth(), manila.getUTCDate()) / 86400000,
  );
  const spans = pastSpans(text);
  const spaced = pastSpaced(text);
  const inserts: number[] = [];
  let i = 0;
  while (i < spans.length) {
    let pick = spans[i];
    if (i + 1 < spans.length) {
      const next = spans[i + 1];
      const joiner = pastTrimAscii(spaced.slice(pick.end, next.start)).toLowerCase();
      if (PAST_RANGE_JOINERS.indexOf(joiner) !== -1) {
        pick = next;
        i++;
      }
    }
    i++;
    const year = pick.year !== null ? pick.year : pastResolveYear(pick.month, pick.day, sources);
    if (year === null) continue;
    const dayNumber = pastDayNumber(year, pick.month, pick.day);
    if (dayNumber !== null && dayNumber < today) inserts.push(pick.end);
  }
  inserts.sort((a, b) => b - a);
  let out = text;
  for (const at of inserts) out = out.slice(0, at) + PAST_DATE_NOTE + out.slice(at);
  return out;
}

/** The cited sources of an AI answer: every listed result. */
export function pastResultSources(results: Announcement[]): string[] {
  return results.map((r) => r.title + "\n" + r.excerpt);
}
