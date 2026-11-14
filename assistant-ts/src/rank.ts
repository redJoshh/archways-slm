/**
 * rank_v1 on the phone: a port of src/archways_assistant/rank.py.
 *
 * The rule is docs/plans/accuracy-phase.md, "rank_v1 rule, pre-registered"
 * (2026-11-14), checked by the hand-written tests/vectors/rank_vectors.json.
 *
 * - Question anchors: claims(question lowercased) from guard-ts: its dates,
 *   and its numbers (a date's year is a number, its day is not).
 * - Content words: the lowercased question with parsed dates blanked, split
 *   into runs of word characters (isWordChar); tokens with a decimal digit
 *   (DIGIT_RANGES), tokens of one code point, STOPWORDS and RANK_STOPWORDS
 *   dropped; first occurrence kept, in order.
 * - Per row (the index's lowercased title and whole plain-text body): a word
 *   is found by the matcher's test for a one-word query; a date anchor in the
 *   claims of title + "\n" + body; a number anchor in its numbers or its
 *   dates' day numbers (Python merged_claims).
 * - points = words found + ANCHOR_WEIGHT x anchors found.
 *
 * Documented gap: toLowerCase() can differ from Python's str.lower() for some
 * non-ASCII text (as in search.ts).
 */

import { claims, claimsAndRest, type Claims } from "../../guard-ts/src/guard.ts";
import { ANCHOR_WEIGHT, DIGIT_RANGES, RANK_STOPWORDS, STOPWORDS, SYNONYMS } from "./searchData.ts";
import { isWordChar, pluralAlternative, synonymsFor, wholeWordIn, type IndexRow, type Matcher } from "./search.ts";

type SynonymMap = { readonly [word: string]: readonly string[] };

export type RankVersion = "rank_v1";

export interface RankTerms {
  words: string[];
  /** "MM-DD" keys. */
  dates: string[];
  /** Canonical decimal strings. */
  numbers: string[];
  possible: number;
}

function inRanges(ranges: readonly number[], codePoint: number): boolean {
  let low = 0;
  let high = ranges.length / 2 - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (codePoint < ranges[2 * mid]) high = mid - 1;
    else if (codePoint > ranges[2 * mid + 1]) low = mid + 1;
    else return true;
  }
  return false;
}

/** Maximal runs of word characters, by code point, in order. */
export function rankTokens(text: string): string[] {
  const out: string[] = [];
  let current = "";
  for (let i = 0; i < text.length; ) {
    const cp = text.codePointAt(i) as number;
    const width = cp > 0xffff ? 2 : 1;
    if (isWordChar(cp)) current += text.slice(i, i + width);
    else if (current) {
      out.push(current);
      current = "";
    }
    i += width;
  }
  if (current) out.push(current);
  return out;
}

function codePointLength(text: string): number {
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

function hasDigit(token: string): boolean {
  for (let i = 0; i < token.length; ) {
    const cp = token.codePointAt(i) as number;
    if (inRanges(DIGIT_RANGES, cp)) return true;
    i += cp > 0xffff ? 2 : 1;
  }
  return false;
}

export function questionTerms(question: string): RankTerms {
  const found = claimsAndRest(question.toLowerCase());
  const words: string[] = [];
  for (const token of rankTokens(found.rest)) {
    if (
      codePointLength(token) < 2 ||
      hasDigit(token) ||
      STOPWORDS.indexOf(token) !== -1 ||
      RANK_STOPWORDS.indexOf(token) !== -1 ||
      words.indexOf(token) !== -1
    ) {
      continue;
    }
    words.push(token);
  }
  const dates = Object.keys(found.dates).sort();
  const numbers = Object.keys(found.numbers).sort();
  return {
    words: words,
    dates: dates,
    numbers: numbers,
    possible: words.length + ANCHOR_WEIGHT * (dates.length + numbers.length),
  };
}

/** The matcher's (and_v3) test for a one-word query, on lowercased text. */
export function wordFound(word: string, title: string, body: string, synonymMap: SynonymMap = SYNONYMS): boolean {
  const synonyms = Object.prototype.hasOwnProperty.call(synonymMap, word) ? synonymMap[word] : [];
  const alts = [word].concat(synonyms);
  for (const alt of alts) if (title.indexOf(alt) !== -1 || body.indexOf(alt) !== -1) return true;
  const stem = pluralAlternative(word);
  return stem !== null && (wholeWordIn(stem, title) || wholeWordIn(stem, body));
}

interface RowAnchors {
  dates: { [key: string]: true };
  /** Numbers, plus the day numbers of the dates (merged_claims). */
  numbers: { [key: string]: true };
}

// Row claims are computed once per index row and kept (the rule's
// "computed once at index time"); rows are immutable once indexed.
const rowCache: WeakMap<IndexRow, RowAnchors> = new WeakMap();

function rowAnchors(row: IndexRow): RowAnchors {
  const cached = rowCache.get(row);
  if (cached !== undefined) return cached;
  const own: Claims = claims(row.title + "\n" + row.body);
  const numbers: { [key: string]: true } = {};
  for (const key of Object.keys(own.numbers)) numbers[key] = true;
  for (const key of Object.keys(own.dates)) numbers[String(parseInt(key.slice(3), 10))] = true;
  const anchors = { dates: own.dates, numbers: numbers };
  rowCache.set(row, anchors);
  return anchors;
}

export function rowPoints(terms: RankTerms, row: IndexRow, synonymMap: SynonymMap = SYNONYMS): number {
  let words = 0;
  for (const word of terms.words) if (wordFound(word, row.title, row.body, synonymMap)) words++;
  const anchors = rowAnchors(row);
  let found = 0;
  for (const key of terms.dates) if (anchors.dates[key] === true) found++;
  for (const key of terms.numbers) if (anchors.numbers[key] === true) found++;
  return words + ANCHOR_WEIGHT * found;
}

/**
 * The searchRows score for a rank version and the raw question, or
 * undefined (newest first) when rank is null.
 */
export function rankScorer(
  rank: RankVersion | null,
  question: string,
  matcher: Matcher = "and_v3",
): ((row: IndexRow) => number) | undefined {
  if (rank === null) return undefined;
  if (rank !== "rank_v1") throw new Error("unknown rank version");
  const terms = questionTerms(question);
  const synonymMap = synonymsFor(matcher);
  return (row: IndexRow) => rowPoints(terms, row, synonymMap);
}

export type GateVersion = "gate_v1";

/**
 * gate_v1 (accuracy-phase.md (d)): is the top result about the question?
 * row is the top result's index row (lowercased title and whole body);
 * passes if points x q >= p x possible for theta = p/q; possible 0 passes.
 */
export function gateV1(question: string, row: IndexRow, matcher: Matcher, p: number, q: number): boolean {
  if (!(q > 0) || !(p >= 0)) throw new Error("theta must be p/q with p >= 0 and q > 0");
  const terms = questionTerms(question);
  if (terms.possible === 0) return true;
  return rowPoints(terms, row, synonymsFor(matcher)) * q >= p * terms.possible;
}
