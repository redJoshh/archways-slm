/**
 * contradiction_v1 (v2 fix (a)) on the phone: a port of contradiction.py.
 *
 * Rule: docs/plans/v2-improvements.md, "contradiction_v1 rule,
 * pre-registered" (2026-11-18), checked by the hand-written
 * tests/vectors/contradiction_vectors.json.
 *
 * On a reply the guard passed, it fires when (1) the question has a
 * permission trigger phrase, (2) a listed result's title + "\n" + excerpt
 * has a prohibition marker phrase, and (3) the reply asserts permission
 * (first token yes/oo/opo, or a permission token with no negation among the
 * up to 3 tokens before it). Tokens: lowercased, maximal runs of and_v3 word
 * characters (isWordChar); an apostrophe (U+0027 or U+2019) between two word
 * characters joins the token as U+0027. Phrases match as consecutive tokens.
 *
 * Known limit: a reply that echoes a Taglish "Pwede ...?" question is
 * blocked even when it then states the prohibition (rules10 r02).
 */

import type { Announcement } from "./render.ts";
import { isWordChar } from "./search.ts";

export type ContradictionRule = "contradiction_v1" | null;
export const CONTRADICTION_CODE = "contradiction";

const CONTRA_TRIGGERS: readonly string[] = [
  "can i", "can we", "can students", "may i", "may we", "is it allowed", "are we allowed", "am i allowed",
  "allowed ba", "pwede ba", "puwede ba", "pwede", "puwede", "bawal ba",
];
const CONTRA_MARKERS: readonly string[] = [
  "prohibited", "not allowed", "not permitted", "strictly prohibited", "strictly not allowed",
  "bawal", "forbidden", "banned", "must not",
];
const CONTRA_YES_FIRST: readonly string[] = ["yes", "oo", "opo"];
const CONTRA_PERMISSION: readonly string[] = ["allowed", "permitted", "encouraged", "pwede", "puwede", "can"];
const CONTRA_NEGATIONS: readonly string[] = ["not", "never", "no", "hindi", "bawal", "cannot", "can't"];
const CONTRA_WINDOW = 3;
const CONTRA_APOSTROPHE = 0x27;
const CONTRA_RIGHT_QUOTE = 0x2019;

function contraCodePoints(text: string): number[] {
  const out: number[] = [];
  for (let i = 0; i < text.length; i++) {
    const cp = text.codePointAt(i) as number;
    out.push(cp);
    if (cp > 0xffff) i++;
  }
  return out;
}

/** The rule's tokens of text. */
export function contradictionTokens(text: string): string[] {
  const cps = contraCodePoints(text.toLowerCase());
  const out: string[] = [];
  let current = "";
  for (let i = 0; i < cps.length; i++) {
    const cp = cps[i];
    if (isWordChar(cp)) current += String.fromCodePoint(cp);
    else if (
      (cp === CONTRA_APOSTROPHE || cp === CONTRA_RIGHT_QUOTE) &&
      current !== "" &&
      i + 1 < cps.length &&
      isWordChar(cps[i + 1])
    ) {
      current += String.fromCharCode(CONTRA_APOSTROPHE);
    } else if (current !== "") {
      out.push(current);
      current = "";
    }
  }
  if (current !== "") out.push(current);
  return out;
}

function contraHasPhrase(words: string[], phrase: string): boolean {
  const parts = phrase.split(" ");
  for (let start = 0; start + parts.length <= words.length; start++) {
    let all = true;
    for (let k = 0; k < parts.length; k++) if (words[start + k] !== parts[k]) all = false;
    if (all) return true;
  }
  return false;
}

export function assertsPermission(reply: string): boolean {
  const words = contradictionTokens(reply);
  if (words.length > 0 && CONTRA_YES_FIRST.indexOf(words[0]) !== -1) return true;
  for (let i = 0; i < words.length; i++) {
    if (CONTRA_PERMISSION.indexOf(words[i]) === -1) continue;
    let negated = false;
    for (let j = Math.max(0, i - CONTRA_WINDOW); j < i; j++) if (CONTRA_NEGATIONS.indexOf(words[j]) !== -1) negated = true;
    if (!negated) return true;
  }
  return false;
}

/** Whether contradiction_v1 blocks this guard-passed reply. */
export function contradictionFires(
  question: string,
  reply: string,
  results: readonly { title: string; excerpt: string }[],
): boolean {
  const q = contradictionTokens(question);
  let triggered = false;
  for (const p of CONTRA_TRIGGERS) if (!triggered && contraHasPhrase(q, p)) triggered = true;
  if (!triggered) return false;
  let marked = false;
  for (const r of results) {
    if (marked) break;
    const words = contradictionTokens(r.title + "\n" + r.excerpt);
    for (const p of CONTRA_MARKERS) if (!marked && contraHasPhrase(words, p)) marked = true;
  }
  return marked && assertsPermission(reply);
}

/** null: off. Throws on an unknown rule. */
export function contradictionBlocks(rule: ContradictionRule, question: string, reply: string, results: Announcement[]): boolean {
  if (rule === null) return false;
  if (rule !== "contradiction_v1") throw new Error("unknown contradiction rule " + String(rule));
  return contradictionFires(question, reply, results);
}
