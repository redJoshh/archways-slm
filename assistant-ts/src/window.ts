/**
 * excerpt_v2_centred on the phone: a port of src/archways_assistant/window.py.
 *
 * Rule: docs/plans/accuracy-phase.md, "excerpt_v2_centred rule,
 * pre-registered" (2026-11-14), checked by tests/vectors/window_vectors.json.
 * Every position is in code points (the rule's unit), never UTF-16 units.
 */

import { claimsAndRest } from "../../guard-ts/src/guard.ts";
import { questionTerms } from "./rank.ts";
import { isWordChar, pluralAlternative, queryGroups, synonymsFor, type IndexRow, type Matcher } from "./search.ts";
import { EXCERPT_CHARS } from "./searchData.ts";

export type ExcerptRule = "excerpt_v2_centred";

const WINDOW_LEAD = 250;
const WINDOW_SNAP = 30;
const ELLIPSIS = "…";

/** The text as an array of code points (each a string of 1 or 2 units). */
function codePointArray(text: string): string[] {
  const out: string[] = [];
  for (let i = 0; i < text.length; ) {
    const cp = text.codePointAt(i) as number;
    const width = cp > 0xffff ? 2 : 1;
    out.push(text.slice(i, i + width));
    i += width;
  }
  return out;
}

/** Code point index of a UTF-16 unit offset in text. */
function unitToCodePoint(text: string, unit: number): number {
  let n = 0;
  for (let i = 0; i < unit; ) {
    const cp = text.codePointAt(i) as number;
    i += cp > 0xffff ? 2 : 1;
    n++;
  }
  return n;
}

function firstWholeWord(stem: string, text: string): number {
  let start = text.indexOf(stem);
  while (start !== -1) {
    const end = start + stem.length;
    let before = true;
    if (start > 0) {
      const low = text.charCodeAt(start - 1);
      const prev =
        low >= 0xdc00 && low <= 0xdfff && start >= 2 ? (text.codePointAt(start - 2) as number) : low;
      before = !isWordChar(prev);
    }
    const after = end >= text.length || !isWordChar(text.codePointAt(end) as number);
    if (before && after) return start;
    start = text.indexOf(stem, start + 1);
  }
  return -1;
}

type Span = [number, number];

function better(candidate: Span, best: Span | null): boolean {
  return best === null || candidate[0] < best[0] || (candidate[0] === best[0] && candidate[1] < best[1]);
}

/** Earliest substring alt or whole-word stem, as code point [start, end). */
function earliest(groups: [string[], string[]][], text: string): Span | null {
  let best: Span | null = null;
  for (const [subs, stems] of groups) {
    for (const alt of subs) {
      const i = text.indexOf(alt);
      if (i === -1) continue;
      const span: Span = [unitToCodePoint(text, i), unitToCodePoint(text, i + alt.length)];
      if (better(span, best)) best = span;
    }
    for (const stem of stems) {
      const i = firstWholeWord(stem, text);
      if (i === -1) continue;
      const span: Span = [unitToCodePoint(text, i), unitToCodePoint(text, i + stem.length)];
      if (better(span, best)) best = span;
    }
  }
  return best;
}

/** The window's anchor in the body, as code point [start, end), or null. */
export function windowAnchor(body: string, question: string, query: string, matcher: Matcher): Span | null {
  const lowered = body.toLowerCase();
  const terms = questionTerms(question);
  if (terms.dates.length > 0) {
    let best: Span | null = null;
    for (const span of claimsAndRest(lowered).spans) {
      if (terms.dates.indexOf(span.date) === -1) continue;
      const cp: Span = [unitToCodePoint(lowered, span.start), unitToCodePoint(lowered, span.end)];
      if (better(cp, best)) best = cp;
    }
    if (best !== null) return best;
  }
  const synonymMap = synonymsFor(matcher);
  const words: [string[], string[]][] = terms.words.map((w) => {
    const synonyms = Object.prototype.hasOwnProperty.call(synonymMap, w) ? synonymMap[w] : [];
    const stem = pluralAlternative(w);
    return [[w].concat(synonyms), stem === null ? [] : [stem]];
  });
  const byWord = earliest(words, lowered);
  if (byWord !== null) return byWord;
  return earliest(queryGroups(query, synonymMap), lowered);
}

export function centredExcerpt(body: string, question: string, query: string, matcher: Matcher): string {
  const cps = codePointArray(body);
  const first = cps.slice(0, EXCERPT_CHARS).join("");
  if (codePointArray(body.toLowerCase()).length !== cps.length) return first;
  const anchor = windowAnchor(body, question, query, matcher);
  if (anchor === null || anchor[1] <= EXCERPT_CHARS) return first;
  let start = Math.max(0, Math.min(anchor[0] - WINDOW_LEAD, cps.length - EXCERPT_CHARS));
  if (start > 0 && cps[start - 1] !== " ") {
    const stop = Math.min(start + WINDOW_SNAP, cps.length);
    for (let i = start; i < stop; i++) {
      if (cps[i] === " ") {
        start = i + 1;
        break;
      }
    }
  }
  if (start === 0) return first;
  return ELLIPSIS + cps.slice(start, start + EXCERPT_CHARS - 1).join("");
}

/** searchRows's excerptFor for a rule, or undefined (the first 500). */
export function excerptFor(
  rule: ExcerptRule | null,
  question: string,
  matcher: Matcher,
): ((row: IndexRow, query: string) => string) | undefined {
  if (rule === null) return undefined;
  if (rule !== "excerpt_v2_centred") throw new Error("unknown excerpt rule");
  return (row: IndexRow, query: string) => centredExcerpt(row.plain, question, query, matcher);
}
