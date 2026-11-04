/**
 * Answer guard: a TypeScript port of guard() in
 * src/archways_assistant/e2escore.py. Zero dependencies, no clock, no I/O.
 *
 * A reply's dates and numbers are claims. Each must be supported by the
 * retrieved titles and excerpts or the question; posted dates and today's
 * date never count. If a claim is unsupported, the reply has a decimal
 * digit outside 0-9, or it contains the title of a row that must never
 * reach the model, the reply is replaced by fallback(results): a list
 * built only from the retrieved titles and posted dates. If that list
 * can't be built (an unreadable posted_at), the reply is
 * LAST_RESORT_MESSAGE.
 *
 * Parity with Python is defined on fired, codes and text and checked by
 * tests/vectors/guard_vectors.json. reasons are for people and may
 * differ. Written for old JS engines (Hermes): no classes, no lookbehind,
 * no named groups, no \p{...}, no `u` flag.
 */

import {
  FALLBACK_HEADER,
  GUARD_SPACES,
  LAST_RESORT_MESSAGE,
  NON_ASCII_DIGIT_RANGES,
} from "./spec.ts";

export { FALLBACK_HEADER, LAST_RESORT_MESSAGE };

export interface Announcement {
  id: string;
  title: string;
  excerpt: string;
  office: string;
  priority: string;
  year_level: number | null;
  posted_at: string;
}

export interface GuardResult {
  /** The text to show the student. */
  text: string;
  fired: boolean;
  /** unsupported_date:MM-DD, unsupported_number:N, non_ascii_digit,
   * filtered_text:I (I indexes forbidden), in that order. */
  codes: string[];
  /** Human-readable, one per code; not part of parity. */
  reasons: string[];
}

const MONTHS: { [key: string]: number } = {
  jan: 1,
  feb: 2,
  mar: 3,
  apr: 4,
  may: 5,
  jun: 6,
  jul: 7,
  aug: 8,
  sep: 9,
  oct: 10,
  nov: 11,
  dec: 12,
};
const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

// Python's re.ASCII semantics: \s is exactly [ \t\n\r\f\v] (JS's \s is
// wider), \b and \d are ASCII in JS without the u flag, and the i flag
// without u folds only ASCII letters for these ASCII patterns.
const WS = "[ \\t\\n\\r\\f\\v]";
const MONTH =
  "(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?" +
  "|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)";
const ORDINAL = "(?:st|nd|rd|th)?";
const YEAR = "(?:," + "?" + WS + "+([0-9]{4}))?";

interface DatePattern {
  regex: RegExp;
  month: number;
  day: number;
  year: number;
}

// Same order as Python's DATE_PATTERNS; group numbers replace names.
const DATE_PATTERNS: DatePattern[] = [
  // November 6, Nov. 6th, November 6, 2026
  {
    regex: new RegExp(
      "\\b" + MONTH + "\\.?" + WS + "+([0-9]{1,2})" + ORDINAL + "\\b" + YEAR,
      "gi",
    ),
    month: 1,
    day: 2,
    year: 3,
  },
  // 6 November, 6th of Nov 2026
  {
    regex: new RegExp(
      "\\b([0-9]{1,2})" +
        ORDINAL +
        WS +
        "+(?:of" +
        WS +
        "+)?" +
        MONTH +
        "\\b\\.?" +
        YEAR,
      "gi",
    ),
    month: 2,
    day: 1,
    year: 3,
  },
  // 2026-11-06
  {
    regex: /\b([0-9]{4})-([0-9]{2})-([0-9]{2})\b/g,
    month: 2,
    day: 3,
    year: 1,
  },
];
const NUMBER = /[0-9]+/g;
const SPACES = new RegExp(
  "[" + GUARD_SPACES.map((cp) => "\\u" + hex4(cp)).join("") + "]",
  "g",
);
const POSTED_AT =
  /^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]+)?(?:[Zz]|[+-]([0-9]{2}):([0-9]{2}))$/;

function hex4(cp: number): string {
  const text = cp.toString(16);
  return "0000".slice(text.length) + text;
}

function pad2(n: number): string {
  return n < 10 ? "0" + n : String(n);
}

/** A digit string as Python's str(int(...)): no leading zeros, any size. */
function canonical(digits: string): string {
  let i = 0;
  while (i < digits.length - 1 && digits.charAt(i) === "0") i++;
  return digits.slice(i);
}

/** Numeric order for canonical non-negative integers. */
function compareNumbers(a: string, b: string): number {
  if (a.length !== b.length) return a.length - b.length;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** "MM-DD" keys sort like Python's (month, day) tuples. */
function compareStrings(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

interface Claims {
  dates: { [key: string]: true };
  numbers: { [key: string]: true };
}

/** The (month, day) dates and the other integers in the text. */
function claims(text: string): Claims {
  const dates: { [key: string]: true } = {};
  const numbers: { [key: string]: true } = {};
  // Code units; every match is ASCII, so blanking a unit blanks a code point.
  const chars = text.replace(SPACES, " ").split("");
  for (const pattern of DATE_PATTERNS) {
    const snapshot = chars.join("");
    pattern.regex.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.regex.exec(snapshot)) !== null) {
      const monthText = match[pattern.month];
      const month = /^[0-9]+$/.test(monthText)
        ? parseInt(monthText, 10)
        : MONTHS[monthText.slice(0, 3).toLowerCase()];
      const day = parseInt(match[pattern.day], 10);
      if (!(month >= 1 && month <= 12 && day >= 1 && day <= 31)) continue;
      dates[pad2(month) + "-" + pad2(day)] = true;
      const year = match[pattern.year];
      if (year) numbers[canonical(year)] = true;
      // Blank the date so its digits aren't read again as numbers.
      for (let i = match.index; i < match.index + match[0].length; i++) {
        chars[i] = " ";
      }
    }
  }
  const rest = chars.join("");
  NUMBER.lastIndex = 0;
  let token: RegExpExecArray | null;
  while ((token = NUMBER.exec(rest)) !== null) {
    numbers[canonical(token[0])] = true;
  }
  return { dates, numbers };
}

/** What a reply may claim: retrieved titles and excerpts, and the question. */
function supported(results: Announcement[], question: string): Claims {
  const texts = results.map((r) => r.title + "\n" + r.excerpt);
  texts.push(question);
  const dates: { [key: string]: true } = {};
  const numbers: { [key: string]: true } = {};
  for (const text of texts) {
    const found = claims(text);
    for (const key of Object.keys(found.dates)) dates[key] = true;
    for (const key of Object.keys(found.numbers)) numbers[key] = true;
  }
  // Text dates also support their bare day numbers in a reply.
  for (const key of Object.keys(dates)) {
    numbers[String(parseInt(key.slice(3), 10))] = true;
  }
  return { dates, numbers };
}

function hasNonAsciiDigit(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    let cp = text.charCodeAt(i);
    if (cp < 0x80) continue;
    if (cp >= 0xd800 && cp <= 0xdbff && i + 1 < text.length) {
      const low = text.charCodeAt(i + 1);
      if (low >= 0xdc00 && low <= 0xdfff) {
        cp = (cp - 0xd800) * 0x400 + (low - 0xdc00) + 0x10000;
        i++;
      }
    }
    for (const [first, last] of NON_ASCII_DIGIT_RANGES) {
      if (cp >= first && cp <= last) return true;
    }
  }
  return false;
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

/** The wall-clock date of a contract posted_at; throws for anything else.
 *
 * Accepted: YYYY-MM-DDTHH:MM:SS, an optional fraction, then Z or +/-HH:MM
 * (T and Z in either case, ASCII digits). Year 1 or later, a real calendar
 * day, hour up to 23, minute and second up to 59 (no leap second), offset
 * up to 23:59. No time-zone conversion; never uses Date. */
export function postedDate(text: string): {
  year: number;
  month: number;
  day: number;
} {
  const match = typeof text === "string" ? POSTED_AT.exec(text) : null;
  if (!match) throw new Error("not a contract posted_at: " + String(text));
  const n = (i: number) => parseInt(match[i], 10);
  const [year, month, day, hour, minute, second] = [n(1), n(2), n(3), n(4), n(5), n(6)];
  if (hour > 23 || minute > 59 || second > 59) {
    throw new Error("time out of range: " + text);
  }
  if (match[7] !== undefined && (n(7) > 23 || n(8) > 59)) {
    throw new Error("offset out of range: " + text);
  }
  const monthDays = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > monthDays[month - 1]) {
    throw new Error("date out of range: " + text);
  }
  return { year, month, day };
}

/** A reply built only from retrieved titles and posted dates. */
export function fallback(results: Announcement[]): string {
  const lines = [FALLBACK_HEADER];
  for (const result of results) {
    if (typeof result.title !== "string") throw new Error("result has no title");
    const posted = postedDate(result.posted_at);
    lines.push(
      "- " +
        result.title +
        " (posted " +
        MONTH_NAMES[posted.month - 1] +
        " " +
        posted.day +
        ", " +
        posted.year +
        ")",
    );
  }
  return lines.join("\n");
}

/** Replace the reply with fallback(results) if it has an unsupported claim,
 * a non-ASCII digit or forbidden text (the titles of rows that must never
 * reach the model). The fallback is built only when the guard fires. */
export function guard(
  reply: string,
  results: Announcement[],
  question: string,
  forbidden: string[],
): GuardResult {
  const made = claims(reply);
  const allowed = supported(results, question);
  const codes: string[] = [];
  const reasons: string[] = [];
  for (const key of Object.keys(made.dates).sort(compareStrings)) {
    if (allowed.dates[key]) continue;
    codes.push("unsupported_date:" + key);
    reasons.push("date " + key);
  }
  for (const key of Object.keys(made.numbers).sort(compareNumbers)) {
    if (allowed.numbers[key]) continue;
    codes.push("unsupported_number:" + key);
    reasons.push("number " + key);
  }
  if (hasNonAsciiDigit(reply)) {
    codes.push("non_ascii_digit");
    reasons.push("non-ASCII digit");
  }
  const lowered = reply.toLowerCase();
  forbidden.forEach((title, index) => {
    if (lowered.indexOf(title.toLowerCase()) !== -1) {
      codes.push("filtered_text:" + index);
      reasons.push("filtered text " + JSON.stringify(title));
    }
  });
  if (codes.length === 0) {
    return { text: reply, fired: false, codes, reasons };
  }
  let text: string;
  try {
    text = fallback(results);
  } catch {
    text = LAST_RESORT_MESSAGE;
  }
  return { text, fired: true, codes, reasons };
}
