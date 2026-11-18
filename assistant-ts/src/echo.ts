/**
 * echo_v1 (v2 fix (b)) on the phone: a port of echo.py.
 *
 * Rule: docs/plans/v2-improvements.md, "echo_v1 rule, pre-registered"
 * (2026-11-18), checked by the hand-written tests/vectors/echo_vectors.json.
 *
 * On a reply the guard passed (and contradiction_v1 didn't block), with
 * rank_v1's terms (questionTerms) of the question and of the reply, each
 * content word replaced by pluralAlternative when it has one, it fires when
 * the reply's dates and numbers are subsets of the question's and at most 2
 * distinct normalised reply words are not normalised question words. Then
 * the flow shows the list (answer_not_found, code "echo").
 */

import { questionTerms } from "./rank.ts";
import { pluralAlternative } from "./search.ts";

export type EchoRule = "echo_v1" | null;
export const ECHO_CODE = "echo";
const ECHO_MAX_NEW_WORDS = 2;

function echoNormalised(words: string[]): string[] {
  const out: string[] = [];
  for (const word of words) {
    const stem = pluralAlternative(word);
    const value = stem === null ? word : stem;
    if (out.indexOf(value) === -1) out.push(value);
  }
  return out;
}

function echoSubset(small: string[], big: string[]): boolean {
  for (const item of small) if (big.indexOf(item) === -1) return false;
  return true;
}

/** Whether echo_v1 treats this guard-passed reply as answer_not_found. */
export function isEcho(question: string, reply: string): boolean {
  const asked = questionTerms(question);
  const said = questionTerms(reply);
  if (!echoSubset(said.dates, asked.dates) || !echoSubset(said.numbers, asked.numbers)) return false;
  const askedWords = echoNormalised(asked.words);
  let fresh = 0;
  for (const word of echoNormalised(said.words)) if (askedWords.indexOf(word) === -1) fresh++;
  return fresh <= ECHO_MAX_NEW_WORDS;
}

/** null: off. Throws on an unknown rule. */
export function echoBlocks(rule: EchoRule, question: string, reply: string): boolean {
  if (rule === null) return false;
  if (rule !== "echo_v1") throw new Error("unknown echo rule " + String(rule));
  return isEcho(question, reply);
}
