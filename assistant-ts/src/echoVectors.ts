/**
 * Runs tests/vectors/echo_vectors.json (v2 fix (b)) against the port,
 * without node APIs, so the same check runs under node and Hermes.
 */

import { isEcho } from "./echo.ts";

export interface EchoVectorFile {
  format: string;
  rule: "echo_v1";
  cases: { name: string; question: string; reply: string; expected: boolean }[];
}

export interface EchoVectorReport {
  total: number;
  passed: number;
  failed: number;
  failures: string[];
}

export function runEchoVectors(file: EchoVectorFile): EchoVectorReport {
  const failures: string[] = [];
  let total = 0;
  for (const c of file.cases) {
    total++;
    let got: boolean | null = null;
    try {
      got = isEcho(c.question, c.reply);
    } catch (error) {
      got = null;
    }
    if (got !== c.expected) failures.push("echo " + c.name);
  }
  return { total: total, passed: total - failures.length, failed: failures.length, failures: failures };
}
