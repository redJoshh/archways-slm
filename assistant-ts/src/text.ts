/**
 * Text helpers with explicit semantics (no locale, no Unicode tables
 * beyond the frozen lists in generated.ts). Written for old JS engines
 * (Hermes): no classes, no lookbehind, no named groups, no \p{...}, no `u`
 * flag.
 */

import { ECMA_WHITESPACE } from "./generated.ts";

const ECMA_SPACE: { [code: number]: true } = {};
for (const code of ECMA_WHITESPACE) ECMA_SPACE[code] = true;

const ASCII_SPACE: { [code: number]: true } = {
  0x20: true,
  0x09: true,
  0x0a: true,
  0x0d: true,
  0x0c: true,
  0x0b: true,
};

/** Length in code points; a lone surrogate counts as one. */
export function codePoints(text: string): number {
  let count = 0;
  for (let i = 0; i < text.length; i++) {
    const unit = text.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) i++;
    }
    count++;
  }
  return count;
}

export function hasLoneSurrogate(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    const unit = text.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = i + 1 < text.length ? text.charCodeAt(i + 1) : 0;
      if (next >= 0xdc00 && next <= 0xdfff) {
        i++;
        continue;
      }
      return true;
    }
    if (unit >= 0xdc00 && unit <= 0xdfff) return true;
  }
  return false;
}

/** True if every character is ECMA-262 WhiteSpace or LineTerminator ("" too). */
export function isAllEcmaWhitespace(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    if (!ECMA_SPACE[text.charCodeAt(i)]) return false;
  }
  return true;
}

/** Python's str.strip(" \t\n\r\f\v"): ASCII whitespace only. */
export function trimAscii(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && ASCII_SPACE[text.charCodeAt(start)]) start++;
  while (end > start && ASCII_SPACE[text.charCodeAt(end - 1)]) end--;
  return text.slice(start, end);
}

export function replaceAll(text: string, search: string, replacement: string): string {
  return text.split(search).join(replacement);
}
