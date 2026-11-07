/**
 * The contract's plain-text rule (a port of src/archways_assistant/excerpt.py
 * plain_text()), applied to feed detail bodies on the phone (ADR 0006):
 *
 * 1. Strip tags: "<" followed by a letter, "/" or "!", up to the next ">".
 *    INLINE_TAGS are removed; every other tag becomes one space.
 * 2. Decode references with a closing ";": HTML5 named (ENTITIES, own
 *    properties only), &#NNN; and &#xHH;. 0, a surrogate or above U+10FFFF
 *    becomes U+FFFD. Anything else stays as written.
 * 3. Each run of PLAIN_SPACE becomes one space; leading and trailing
 *    spaces are dropped.
 * cutCodePoints() then cuts to EXCERPT_CHARS code points.
 */

import { ENTITIES, INLINE_TAGS, PLAIN_SPACE } from "./searchData.ts";

const TAG = /<([A-Za-z/!])[^>]*>/g;
const TAG_NAME = /^<\/?([A-Za-z][A-Za-z0-9]*)/;
const REFERENCE = /&(#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);/g;
const REPLACEMENT = String.fromCharCode(0xfffd);

const PLAIN_SPACE_SET: { [ch: string]: boolean } = {};
for (const code of PLAIN_SPACE) PLAIN_SPACE_SET[String.fromCharCode(code)] = true;

function stripTags(body: string): string {
  return body.replace(TAG, (tag: string) => {
    const name = TAG_NAME.exec(tag);
    return name && INLINE_TAGS.indexOf(name[1].toLowerCase()) !== -1 ? "" : " ";
  });
}

function decodeReferences(text: string): string {
  return text.replace(REFERENCE, (whole: string, token: string) => {
    if (token.charAt(0) === "#") {
      const digits = token.slice(1);
      const hex = digits.charAt(0) === "x" || digits.charAt(0) === "X";
      const code = hex ? parseInt(digits.slice(1), 16) : parseInt(digits, 10);
      if (!(code >= 1 && code <= 0x10ffff) || (code >= 0xd800 && code <= 0xdfff)) return REPLACEMENT;
      return String.fromCodePoint(code);
    }
    return Object.prototype.hasOwnProperty.call(ENTITIES, token) ? ENTITIES[token] : whole;
  });
}

function collapse(text: string): string {
  let out = "";
  let inRun = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charAt(i);
    if (PLAIN_SPACE_SET[ch] === true) {
      inRun = true;
      continue;
    }
    if (inRun && out.length > 0) out += " ";
    inRun = false;
    out += ch;
  }
  return out;
}

/** Steps 1-3: the body as plain text, before the cut. */
export function plainText(body: string): string {
  return collapse(decodeReferences(stripTags(body)));
}

/** The first n code points of text (Python's text[:n]). */
export function cutCodePoints(text: string, n: number): string {
  let count = 0;
  let i = 0;
  while (i < text.length && count < n) {
    const code = text.charCodeAt(i);
    const pair = code >= 0xd800 && code <= 0xdbff && i + 1 < text.length;
    const next = pair ? text.charCodeAt(i + 1) : 0;
    i += pair && next >= 0xdc00 && next <= 0xdfff ? 2 : 1;
    count++;
  }
  return text.slice(0, i);
}

/** Code points in text (Python's len(); a lone surrogate counts as one). */
export function countCodePoints(text: string): number {
  let count = 0;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) i++;
    }
    count++;
  }
  return count;
}
