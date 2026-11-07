/**
 * The and_v3 matcher on the phone (ADR 0006): a port of fakebackend.py's
 * and_v3 and feedindex.search_feed().
 *
 * - The query is lowercased (toLowerCase) and split on PY_SPACE (Python's
 *   str.isspace()); STOPWORDS are dropped. No words left: no results.
 * - Each word is a group: the word and its SYNONYMS match as substrings of
 *   the lowercased title or plain-text body; the plural alternative
 *   (pluralAlternative) matches only as a whole word. OR within a group,
 *   AND across groups.
 * - Window: now - days <= published <= now (days default DAYS_DEFAULT).
 * - Order: newest published first, then id ascending; pinned is ignored.
 *   Then limit (default LIMIT_DEFAULT).
 *
 * Word characters are "_", Unicode letters (L*) and decimal digits (Nd),
 * judged per code point by WORD_RANGES, generated from Python's unicodedata,
 * so the engine's own Unicode data never decides. Documented gap:
 * toLowerCase() can differ from Python's str.lower() for some non-ASCII text.
 */

import { checkArguments } from "./contract.ts";
import type { Announcement } from "./render.ts";
import { countCodePoints } from "./plaintext.ts";
import { DAYS_DEFAULT, LIMIT_DEFAULT, PY_SPACE, STOPWORDS, SYNONYMS, WORD_RANGES } from "./searchData.ts";

/** One indexed feed item. */
export interface IndexRow {
  announcement: Announcement;
  /** Lowercased title and lowercased whole plain-text body, for matching. */
  title: string;
  body: string;
  publishedMs: number;
}

const DAY_MS = 86400000;

const PY_SPACE_SET: { [ch: string]: boolean } = {};
for (const code of PY_SPACE) PY_SPACE_SET[String.fromCharCode(code)] = true;

/** "_", L* or Nd, by the generated WORD_RANGES (Python's Unicode data). */
export function isWordChar(codePoint: number): boolean {
  let low = 0;
  let high = WORD_RANGES.length / 2 - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (codePoint < WORD_RANGES[2 * mid]) high = mid - 1;
    else if (codePoint > WORD_RANGES[2 * mid + 1]) low = mid + 1;
    else return true;
  }
  return false;
}

/** The word without its trailing "s" if eligible (fakebackend.plural_alternative). */
export function pluralAlternative(word: string): string | null {
  if (countCodePoints(word) < 5 || word.slice(-1) !== "s") return null;
  const end2 = word.slice(-2);
  if (end2 === "ss" || end2 === "us" || end2 === "is") return null;
  const stem = word.slice(0, -1);
  const first = stem.codePointAt(0);
  const last = lastCodePoint(stem);
  if (first === undefined || last === null || !isWordChar(first) || !isWordChar(last)) return null;
  return stem;
}

function lastCodePoint(text: string): number | null {
  if (text.length === 0) return null;
  const low = text.charCodeAt(text.length - 1);
  if (low >= 0xdc00 && low <= 0xdfff && text.length >= 2) {
    const high = text.charCodeAt(text.length - 2);
    if (high >= 0xd800 && high <= 0xdbff) return text.codePointAt(text.length - 2) as number;
  }
  return low;
}

/** Whether stem occurs in text with no word character just before or after it. */
export function wholeWordIn(stem: string, text: string): boolean {
  let start = text.indexOf(stem);
  while (start !== -1) {
    const end = start + stem.length;
    const before = start === 0 ? null : lastCodePoint(text.slice(0, start));
    const after = end >= text.length ? undefined : text.codePointAt(end);
    if ((before === null || !isWordChar(before)) && (after === undefined || !isWordChar(after))) return true;
    start = text.indexOf(stem, start + 1);
  }
  return false;
}

function splitPython(text: string): string[] {
  const words: string[] = [];
  let current = "";
  for (let i = 0; i < text.length; i++) {
    const ch = text.charAt(i);
    if (PY_SPACE_SET[ch] === true) {
      if (current) words.push(current);
      current = "";
    } else current += ch;
  }
  if (current) words.push(current);
  return words;
}

/** and_v3 groups: [word and its synonyms, [plural alternative] or []]. */
export function queryGroups(query: string): [string[], string[]][] {
  const out: [string[], string[]][] = [];
  for (const word of splitPython(query.toLowerCase())) {
    if (STOPWORDS.indexOf(word) !== -1) continue;
    const synonyms = Object.prototype.hasOwnProperty.call(SYNONYMS, word) ? SYNONYMS[word] : [];
    const stem = pluralAlternative(word);
    out.push([[word].concat(synonyms), stem === null ? [] : [stem]]);
  }
  return out;
}

function matches(row: IndexRow, groups: [string[], string[]][]): boolean {
  for (const [subs, stems] of groups) {
    let hit = false;
    for (const alt of subs) if (row.title.indexOf(alt) !== -1 || row.body.indexOf(alt) !== -1) hit = true;
    for (const stem of stems) if (!hit && (wholeWordIn(stem, row.title) || wholeWordIn(stem, row.body))) hit = true;
    if (!hit) return false;
  }
  return true;
}

/**
 * search_announcements arguments -> contract results, over the index at
 * nowMs. Throws (ContractError) if the arguments break the contract.
 */
export function searchRows(rows: IndexRow[], args: unknown, nowMs: number): Announcement[] {
  const checked = checkArguments(args);
  const days = checked.days === undefined ? DAYS_DEFAULT : checked.days;
  const limit = checked.limit === undefined ? LIMIT_DEFAULT : checked.limit;
  const groups = queryGroups(checked.query);
  if (groups.length === 0) return [];
  const since = nowMs - days * DAY_MS;
  const found = rows.filter((row) => row.publishedMs <= nowMs && row.publishedMs >= since && matches(row, groups));
  found.sort((a, b) => {
    if (a.publishedMs !== b.publishedMs) return b.publishedMs - a.publishedMs;
    const ia = a.announcement.id;
    const ib = b.announcement.id;
    return ia < ib ? -1 : ia > ib ? 1 : 0;
  });
  return found.slice(0, limit).map((row) => row.announcement);
}
