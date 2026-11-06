/**
 * qwen3:0.6b prompt rendering for both calls: a port of render_qwen3() in
 * src/archways_assistant/render.py and of fill_prompt(), system_turn(),
 * case_part() and answer_user_message() in src/archways_assistant/assistant.py.
 *
 * The prompt is exactly what Ollama's qwen3:0.6b template sends with
 * "think": false (checked by scripts/check_render_qwen3.py):
 *
 *   <|im_start|>system\n\n{system}<|im_end|>\n          <- systemTurn(): cached
 *   <|im_start|>user\n{user} /no_think<|im_end|>\n      <- casePart(): per question
 *   <|im_start|>assistant\n<think>\n\n</think>\n\n
 *
 * No start-of-text token. Send it to llama.rn as a raw `prompt`, never
 * through llama.rn's own chat formatting.
 */

import {
  ANSWER_PROMPT_TEXT,
  QUERY_PROMPT_TEXT,
  RESULT_KEYS,
  WEEKDAYS,
} from "./generated.ts";
import { replaceAll } from "./text.ts";

export const QWEN3_STOP: readonly string[] = ["<|im_end|>", "<|im_start|>"];
const NO_THINK = " /no_think";
const OPEN_ASSISTANT = "<|im_start|>assistant\n<think>\n\n</think>\n\n";
const TODAY = "{today}";
const MANILA_OFFSET_MS = 8 * 60 * 60 * 1000; // Asia/Manila: UTC+08:00, no DST

export interface Announcement {
  id: string;
  title: string;
  excerpt: string;
  office: string;
  priority: string;
  year_level: number | null;
  posted_at: string;
}

function pad(value: number, width: number): string {
  let text = String(value);
  while (text.length < width) text = "0" + text;
  return text;
}

/** The Manila weekday and date of an instant, e.g. "Friday, 2026-11-06". */
export function todayText(nowMs: number): string {
  const local = new Date(nowMs + MANILA_OFFSET_MS);
  const weekday = WEEKDAYS[(local.getUTCDay() + 6) % 7];
  return (
    weekday +
    ", " +
    pad(local.getUTCFullYear(), 4) +
    "-" +
    pad(local.getUTCMonth() + 1, 2) +
    "-" +
    pad(local.getUTCDate(), 2)
  );
}

/** A prompt file's text without its final newline, with {today} filled. */
export function fillPrompt(template: string, nowMs: number): string {
  if (template.indexOf(TODAY) === -1) throw new Error("prompt has no {today} placeholder");
  const body = template.slice(-1) === "\n" ? template.slice(0, -1) : template;
  return replaceAll(body, TODAY, todayText(nowMs));
}

export function querySystem(nowMs: number): string {
  return fillPrompt(QUERY_PROMPT_TEXT, nowMs);
}

export function answerSystem(nowMs: number): string {
  return fillPrompt(ANSWER_PROMPT_TEXT, nowMs);
}

/** The cacheable prefix of a call: its whole system turn. */
export function systemTurn(system: string): string {
  if (system === "") throw new Error("empty system message");
  return "<|im_start|>system\n\n" + system + "<|im_end|>\n";
}

/** The rest of the prompt after systemTurn(): the per-question part. */
export function casePart(user: string): string {
  return "<|im_start|>user\n" + user + NO_THINK + "<|im_end|>\n" + OPEN_ASSISTANT;
}

export function renderQwen3(system: string, user: string): string {
  return systemTurn(system) + casePart(user);
}

/**
 * Python's json.dumps(text, ensure_ascii=False) for text without lone
 * surrogates: \" \\ \b \f \n \r \t, other characters below U+0020 as
 * \u00xx (lowercase hex), everything else as is (U+007F, U+2028 and U+2029
 * included).
 */
export function jsonString(text: string): string {
  let out = '"';
  for (let i = 0; i < text.length; i++) {
    const char = text.charAt(i);
    const code = text.charCodeAt(i);
    if (char === '"') out += '\\"';
    else if (char === "\\") out += "\\\\";
    else if (char === "\b") out += "\\b";
    else if (char === "\f") out += "\\f";
    else if (char === "\n") out += "\\n";
    else if (char === "\r") out += "\\r";
    else if (char === "\t") out += "\\t";
    else if (code < 0x20) out += "\\u00" + (code < 16 ? "0" : "") + code.toString(16);
    else out += char;
  }
  return out + '"';
}

/** json.dumps(results, ensure_ascii=False, indent=1), keys in RESULT_KEYS order. */
export function resultsJson(results: readonly Announcement[]): string {
  const items = results.map((result) => {
    const row = result as unknown as { [key: string]: string | number | null };
    const fields = RESULT_KEYS.map((key) => {
      const value = row[key];
      const shown =
        value === null ? "null" : key === "year_level" ? String(value) : jsonString(String(value));
      return '  "' + key + '": ' + shown;
    });
    return " {\n" + fields.join(",\n") + "\n }";
  });
  return "[\n" + items.join(",\n") + "\n]";
}

/** The answer call's user message: the question, then the results as data. */
export function answerUserMessage(question: string, results: readonly Announcement[]): string {
  const data = replaceAll(resultsJson(results), "<", "\\u003c");
  return "Question: " + question + "\n\n<announcements>\n" + data + "\n</announcements>";
}
