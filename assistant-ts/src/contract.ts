/**
 * Query-reply parsing and contract checks: a port of parse_query_reply(),
 * check_arguments(), check_results() and check_question() in
 * src/archways_assistant/assistant.py, against
 * contracts/search_announcements.schema.json.
 *
 * Spec (identical in both languages; checked by assistant_vectors.json):
 * - The query reply is strict JSON for the whole text (JSON.parse: JSON
 *   whitespace around it is allowed; no fences, no prose, no NaN).
 * - Arguments: an object with only query, days, limit. query is a string of
 *   1-200 code points, well-formed Unicode, with at least one character that
 *   is not ECMA-262 whitespace (the schema's "\S"). days 1-30 and limit 1-10
 *   are JSON numbers with an integral value (30.0 counts). Defaults are not
 *   filled in: Spring applies them.
 * - Results: an array of at most 10 objects with exactly the 7 contract
 *   keys, string fields without lone surrogates, title <= 255 and excerpt
 *   <= 500 code points, year_level an integer (|n| < 2^53) or null, and a
 *   posted_at the guard can read (RFC 3339 as in the contract).
 * Anything else throws ContractError-shaped errors (name "ContractError").
 */

import { postedDate } from "../../guard-ts/src/guard.ts";
import {
  ARGUMENT_KEYS,
  DAYS_MAX,
  DAYS_MIN,
  EXCERPT_MAX_CHARS,
  LIMIT_MAX,
  LIMIT_MIN,
  QUERY_MAX_CHARS,
  QUERY_MIN_CHARS,
  QUESTION_MAX_CHARS,
  RESULTS_MAX,
  RESULT_KEYS,
  TITLE_MAX_CHARS,
} from "./generated.ts";
import type { Announcement } from "./render.ts";
import { codePoints, hasLoneSurrogate, isAllEcmaWhitespace } from "./text.ts";

export interface SearchArguments {
  query: string;
  days?: number;
  limit?: number;
}

const STRING_KEYS = ["id", "title", "excerpt", "office", "priority", "posted_at"];
const MAX_SAFE = 9007199254740992; // 2^53

function contractError(message: string): Error {
  const error = new Error(message);
  error.name = "ContractError";
  return error;
}

function has(value: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function isPlainObject(value: unknown): value is { [key: string]: unknown } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isIntegral(value: unknown): value is number {
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value;
}

export function parseQueryReply(text: unknown): SearchArguments {
  if (typeof text !== "string") throw contractError("reply is not text");
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    throw contractError("invalid JSON");
  }
  return checkArguments(value);
}

export function checkArguments(value: unknown): SearchArguments {
  if (!isPlainObject(value)) throw contractError("not an object");
  for (const key of Object.keys(value)) {
    if (ARGUMENT_KEYS.indexOf(key) === -1) throw contractError("unknown key " + key);
  }
  if (!has(value, "query")) throw contractError("missing query");
  const query = value.query;
  if (typeof query !== "string") throw contractError("query is not a string");
  if (hasLoneSurrogate(query)) throw contractError("query has a lone surrogate");
  const length = codePoints(query);
  if (length < QUERY_MIN_CHARS || length > QUERY_MAX_CHARS) {
    throw contractError("query length out of range");
  }
  if (isAllEcmaWhitespace(query)) throw contractError("query has no non-whitespace character");
  const args: SearchArguments = { query: query };
  const bounds: [string, number, number][] = [
    ["days", DAYS_MIN, DAYS_MAX],
    ["limit", LIMIT_MIN, LIMIT_MAX],
  ];
  for (const [key, low, high] of bounds) {
    if (!has(value, key)) continue;
    const number = value[key];
    if (!isIntegral(number)) throw contractError(key + " is not an integer");
    if (number < low || number > high) throw contractError(key + " out of range");
    if (key === "days") args.days = number;
    else args.limit = number;
  }
  return args;
}

export function checkResults(value: unknown): Announcement[] {
  if (!Array.isArray(value)) throw contractError("results are not an array");
  if (value.length > RESULTS_MAX) throw contractError("more than " + RESULTS_MAX + " results");
  return value.map((item: unknown, index: number) => {
    const where = "result " + index;
    if (!isPlainObject(item)) throw contractError(where + " is not an object");
    const keys = Object.keys(item);
    if (keys.length !== RESULT_KEYS.length || RESULT_KEYS.some((key) => !has(item, key))) {
      throw contractError(where + " keys differ from the contract");
    }
    for (const key of STRING_KEYS) {
      const field = item[key];
      if (typeof field !== "string") throw contractError(where + " " + key + " is not a string");
      if (hasLoneSurrogate(field)) throw contractError(where + " " + key + " has a lone surrogate");
    }
    if (codePoints(item.title as string) > TITLE_MAX_CHARS) throw contractError(where + " title too long");
    if (codePoints(item.excerpt as string) > EXCERPT_MAX_CHARS) {
      throw contractError(where + " excerpt too long");
    }
    const year = item.year_level;
    if (year !== null) {
      if (typeof year === "boolean" || !isIntegral(year)) {
        throw contractError(where + " year_level is not an integer or null");
      }
      if (!(year > -MAX_SAFE && year < MAX_SAFE)) throw contractError(where + " year_level out of range");
    }
    try {
      postedDate(item.posted_at as string);
    } catch (error) {
      throw contractError(where + " posted_at is not RFC 3339");
    }
    return {
      id: item.id as string,
      title: item.title as string,
      excerpt: item.excerpt as string,
      office: item.office as string,
      priority: item.priority as string,
      // -0 becomes 0, as Python's int(-0.0).
      year_level: year === null ? null : (year as number) + 0,
      posted_at: item.posted_at as string,
    };
  });
}

export function checkQuestion(question: unknown): string {
  if (typeof question !== "string" || hasLoneSurrogate(question)) {
    throw contractError("question is not text");
  }
  if (isAllEcmaWhitespace(question)) throw contractError("empty question");
  if (codePoints(question) > QUESTION_MAX_CHARS) throw contractError("question too long");
  return question;
}
