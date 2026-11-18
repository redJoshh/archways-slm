/**
 * extract_v1 (v2 fix (d)) on the phone: a port of extract.py.
 *
 * Rule: docs/plans/v2-improvements.md, "extract_v1 rule, pre-registered"
 * (2026-11-18), checked by the hand-written tests/vectors/extract_vectors.json.
 *
 * 1. Classified: a time phrase and no entity phrase in the question's tokens.
 * 2. Reduced terms: questionTerms without the matched time phrases' tokens.
 * 3. Admissible: a reduced word is left, and results[0]'s lowercased title
 *    and excerpt score every reduced word and anchor (rank_v1 points, always
 *    SYNONYMS_V3).
 * 4. Sentences: the title, then the excerpt split at newlines and after
 *    . ! ? + ASCII whitespace + [A-Z0-9] (not after a listed abbreviation,
 *    ASCII case-insensitive); a 500-code-point excerpt drops its last one.
 * 5.-7. The candidate (date or time) with the most points, earlier on ties,
 *    cut to 300 code points at an ASCII space outside date and time spans.
 * 8. The guard must pass the quote. The flow adds (c)'s note.
 *
 * Lengths and cut positions are in code points, as in Python. The time
 * pattern's lookbehind is written out as a scan (Python finditer order).
 */

import { claimsAndRest, guard } from "../../guard-ts/src/guard.ts";
import { GUARD_SPACES } from "../../guard-ts/src/spec.ts";
import { questionTerms, rankTokens, rowPoints, type RankTerms } from "./rank.ts";
import type { Announcement } from "./render.ts";
import type { IndexRow } from "./search.ts";
import { EXCERPT_CHARS, SYNONYMS_V3 } from "./searchData.ts";

export type ExtractRule = "extract_v1" | null;
export const EXTRACT_LABEL = "From the announcement below:";
export const EXTRACT_LABEL_SEPARATOR = "\n";

const EXTRACT_TIME_PHRASES: readonly string[][] = [
  "when",
  "what time",
  "what date",
  "what day",
  "until when",
  "until what time",
  "how long",
  "kailan",
  "hanggang kailan",
  "anong oras",
  "anong araw",
  "anong petsa",
  "ilang araw",
].map((p) => p.split(" "));
const EXTRACT_ENTITY_PHRASES: readonly string[][] = ["which", "who", "what office", "ano ang"].map((p) =>
  p.split(" "),
);
const EXTRACT_ABBREVIATIONS: readonly string[] = [
  "a.y.",
  "no.",
  "st.",
  "dr.",
  "mr.",
  "ms.",
  "sr.",
  "a.m.",
  "p.m.",
  "e.g.",
  "i.e.",
  "vs.",
];
const EXTRACT_ASCII_SPACE = " \t\n\r\f\v";
const EXTRACT_LINES = /[\n\r]+/;
const EXTRACT_BREAK = /[.!?](?=[ \t\n\r\f\v]+[A-Z0-9])/g;
const EXTRACT_TIME_AT = /^[0-9]{1,2}(?::[0-9]{2})?[ ]?(?:a\.m\.|p\.m\.|am|pm|nn|noon|mn)(?![a-z0-9])/i;
const EXTRACT_MAX_QUOTE = 300;
const EXTRACT_ELLIPSIS = "\u2026";

function extractHasPhrase(tokens: string[], phrase: readonly string[]): boolean {
  for (let i = 0; i + phrase.length <= tokens.length; i++) {
    let same = true;
    for (let j = 0; j < phrase.length; j++) {
      if (tokens[i + j] !== phrase[j]) {
        same = false;
        break;
      }
    }
    if (same) return true;
  }
  return false;
}

/** Step 1: the matched time phrases, or null if not classified. */
export function matchedTimePhrases(question: string): string[][] | null {
  const tokens = rankTokens(question.toLowerCase());
  for (const p of EXTRACT_ENTITY_PHRASES) if (extractHasPhrase(tokens, p)) return null;
  const found: string[][] = [];
  for (const p of EXTRACT_TIME_PHRASES) if (extractHasPhrase(tokens, p)) found.push(p.slice());
  return found.length > 0 ? found : null;
}

/** Step 2: rank_v1's terms without the matched time phrases' tokens. */
export function reducedTerms(question: string, phrases: string[][]): RankTerms {
  const terms = questionTerms(question);
  const drop: { [token: string]: true } = {};
  for (const p of phrases) for (const t of p) drop[t] = true;
  const words = terms.words.filter((w) => drop[w] !== true);
  return {
    words: words,
    dates: terms.dates,
    numbers: terms.numbers,
    possible: terms.possible - (terms.words.length - words.length),
  };
}

function extractPointsOn(terms: RankTerms, title: string, body: string): number {
  // A throwaway row: rowPoints reads only the lowercased title and body.
  const row = { title: title, body: body } as unknown as IndexRow;
  return rowPoints(terms, row, SYNONYMS_V3);
}

/** Step 3. */
export function extractAdmissible(terms: RankTerms, top: Announcement): boolean {
  if (terms.words.length === 0) return false;
  return extractPointsOn(terms, top.title.toLowerCase(), top.excerpt.toLowerCase()) === terms.possible;
}

function extractTrimAsciiSpace(text: string): string {
  let a = 0;
  let b = text.length;
  while (a < b && EXTRACT_ASCII_SPACE.indexOf(text.charAt(a)) !== -1) a++;
  while (b > a && EXTRACT_ASCII_SPACE.indexOf(text.charAt(b - 1)) !== -1) b--;
  return text.slice(a, b);
}

function extractAsciiLower(text: string): string {
  return text.replace(/[A-Z]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 32));
}

function extractIsAsciiLetter(ch: string): boolean {
  return (ch >= "a" && ch <= "z") || (ch >= "A" && ch <= "Z");
}

function extractEndsWithAbbreviation(text: string): boolean {
  for (const abbr of EXTRACT_ABBREVIATIONS) {
    const n = abbr.length;
    if (text.length < n || extractAsciiLower(text.slice(text.length - n)) !== abbr) continue;
    if (text.length === n || !extractIsAsciiLetter(text.charAt(text.length - n - 1))) return true;
  }
  return false;
}

function extractSplitLine(line: string): string[] {
  const out: string[] = [];
  let start = 0;
  EXTRACT_BREAK.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = EXTRACT_BREAK.exec(line)) !== null) {
    const end = match.index + 1;
    if (extractEndsWithAbbreviation(line.slice(0, end))) continue;
    out.push(line.slice(start, end));
    start = end;
  }
  out.push(line.slice(start));
  return out;
}

function extractCodePointLength(text: string): number {
  let n = 0;
  for (let i = 0; i < text.length; i++) {
    const unit = text.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) i++;
    }
    n++;
  }
  return n;
}

/** Step 4: the title, then the excerpt's sentences. */
export function extractSentences(top: Announcement): string[] {
  let parts: string[] = [];
  for (const line of top.excerpt.split(EXTRACT_LINES)) {
    for (const s of extractSplitLine(line)) parts.push(extractTrimAsciiSpace(s));
  }
  parts = parts.filter((s) => s !== "");
  if (extractCodePointLength(top.excerpt) === EXCERPT_CHARS && parts.length > 0) parts = parts.slice(0, -1);
  const title = extractTrimAsciiSpace(top.title);
  return (title !== "" ? [title] : []).concat(parts);
}

function extractSpaced(text: string): string {
  let out = "";
  for (let i = 0; i < text.length; i++) {
    out += GUARD_SPACES.indexOf(text.charCodeAt(i)) !== -1 ? " " : text.charAt(i);
  }
  return out;
}

function extractIsAsciiDigit(ch: string): boolean {
  return ch >= "0" && ch <= "9";
}

/** Date spans and time matches, in UTF-16 offsets of text. */
function extractSpans(text: string): { start: number; end: number }[] {
  const out: { start: number; end: number }[] = [];
  for (const s of claimsAndRest(text).spans) out.push({ start: s.start, end: s.end });
  const t = extractSpaced(text);
  let i = 0;
  while (i < t.length) {
    if (extractIsAsciiDigit(t.charAt(i)) && (i === 0 || !extractIsAsciiDigit(t.charAt(i - 1)))) {
      const m = EXTRACT_TIME_AT.exec(t.slice(i));
      if (m !== null) {
        out.push({ start: i, end: i + m[0].length });
        i += m[0].length;
        continue;
      }
    }
    i++;
  }
  return out;
}

/** Step 5. */
export function hasDateOrTime(text: string): boolean {
  return extractSpans(text).length > 0;
}

/** Step 7: the sentence cut to 300 code points, or null. */
export function extractCut(sentence: string): string | null {
  // offsets[k] = the UTF-16 offset of code point k.
  const offsets: number[] = [];
  for (let i = 0; i < sentence.length; i++) {
    offsets.push(i);
    const unit = sentence.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < sentence.length) {
      const next = sentence.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) i++;
    }
  }
  if (offsets.length <= EXTRACT_MAX_QUOTE) return sentence;
  const spans = extractSpans(sentence);
  for (let k = EXTRACT_MAX_QUOTE - 1; k >= 0; k--) {
    const u = offsets[k];
    if (sentence.charAt(u) !== " ") continue;
    let inside = false;
    for (const s of spans) if (s.start < u && u < s.end) inside = true;
    if (inside) continue;
    const head = sentence.slice(0, u);
    let b = head.length;
    while (b > 0 && EXTRACT_ASCII_SPACE.indexOf(head.charAt(b - 1)) !== -1) b--;
    const quote = head.slice(0, b) + EXTRACT_ELLIPSIS;
    return hasDateOrTime(quote) ? quote : null;
  }
  return null;
}

export interface Extract {
  classified: boolean;
  words: string[] | null;
  admissible: boolean;
  sentences: string[] | null;
  guardFired: boolean;
  /** Before (c)'s note; null: no extract. */
  quote: string | null;
}

/** Steps 1-8 on contract-checked results (results[0] is the top). */
export function extractQuote(question: string, results: Announcement[]): Extract {
  const phrases = matchedTimePhrases(question);
  if (phrases === null || results.length === 0) {
    return { classified: false, words: null, admissible: false, sentences: null, guardFired: false, quote: null };
  }
  const terms = reducedTerms(question, phrases);
  const top = results[0];
  if (!extractAdmissible(terms, top)) {
    return { classified: true, words: terms.words, admissible: false, sentences: null, guardFired: false, quote: null };
  }
  const found = extractSentences(top);
  let best: string | null = null;
  let bestPoints = -1;
  for (const sentence of found) {
    if (!hasDateOrTime(sentence)) continue;
    const got = extractPointsOn(terms, sentence.toLowerCase(), "");
    if (got > bestPoints) {
      best = sentence;
      bestPoints = got;
    }
  }
  const quote = best === null ? null : extractCut(best);
  const fired = quote !== null && guard(quote, results, question, []).fired;
  return {
    classified: true,
    words: terms.words,
    admissible: true,
    sentences: found,
    guardFired: fired,
    quote: fired ? null : quote,
  };
}

/** (c)'s cited source for a quote: the quoted row. */
export function extractSourceText(top: Announcement): string {
  return top.title + "\n" + top.excerpt;
}
