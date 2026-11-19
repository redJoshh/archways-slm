// Run the assistant vectors under the Hermes CLI (hermes-engine-cli, Hermes
// 0.12). A smoke test only: the app's Hermes is newer, and a phone run is
// the real Hermes check.
//
// Builds dist-hermes/run-vectors.js from the tsc output (guard-ts and
// assistant-ts, imports and exports stripped, the vector file inlined, plain
// script, no modules), then runs it with the platform's hermes binary. It
// also runs one question through the async driver (askAssistant) with
// scripted dependencies. Zero dependencies.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const vectorsPath =
  process.env.ASSISTANT_VECTORS ??
  join(root, "..", "tests", "vectors", "assistant_vectors.json");

function plainScript(...parts) {
  return readFileSync(join(root, "dist", ...parts), "utf8")
    .replace(/^import[^;]*;\s*$/gm, "")
    .replace(/^export \{[^}]*\};\s*$/gm, "")
    .replace(/^export /gm, "");
}

const feedVectorsPath = join(root, "..", "tests", "vectors", "feed_vectors.json");
const rankVectorsPath = join(root, "..", "tests", "vectors", "rank_vectors.json");
const retryVectorsPath = join(root, "..", "tests", "vectors", "retry_vectors.json");
const andV4VectorsPath = join(root, "..", "tests", "vectors", "and_v4_vectors.json");
const andV5VectorsPath = join(root, "..", "tests", "vectors", "and_v5_vectors.json");
const gateVectorsPath = join(root, "..", "tests", "vectors", "gate_vectors.json");
const windowVectorsPath = join(root, "..", "tests", "vectors", "window_vectors.json");
const stripNfVectorsPath = join(root, "..", "tests", "vectors", "strip_nf_vectors.json");
const fallbackVectorsPath = join(root, "..", "tests", "vectors", "window_fallback_vectors.json");
const contradictionVectorsPath = join(root, "..", "tests", "vectors", "contradiction_vectors.json");
const echoVectorsPath = join(root, "..", "tests", "vectors", "echo_vectors.json");
const pastDateVectorsPath = join(root, "..", "tests", "vectors", "past_date_vectors.json");
const extractVectorsPath = join(root, "..", "tests", "vectors", "extract_vectors.json");
const answerV5VectorsPath = join(root, "..", "tests", "vectors", "answer_v5_vectors.json");

const runner = `
var log = typeof print === "function" ? print : console.log;
var report = runVectors(VECTORS);
log("hermes assistant vectors: " + report.passed + "/" + report.total + " passed, " +
    report.failed + " failed");
for (var i = 0; i < report.failures.length; i++) log("FAIL " + report.failures[i]);
if (report.failed) { throw new Error("vectors failed"); }
var feedReport = runFeedVectors(FEED_VECTORS);
log("hermes feed vectors: " + feedReport.passed + "/" + feedReport.total + " passed, " +
    feedReport.failed + " failed");
for (var j = 0; j < feedReport.failures.length; j++) log("FAIL " + feedReport.failures[j]);
if (feedReport.failed) { throw new Error("feed vectors failed"); }
var rankReport = runRankVectors(RANK_VECTORS);
log("hermes rank vectors: " + rankReport.passed + "/" + rankReport.total + " passed, " +
    rankReport.failed + " failed");
for (var k = 0; k < rankReport.failures.length; k++) log("FAIL " + rankReport.failures[k]);
if (rankReport.failed) { throw new Error("rank vectors failed"); }
var retryReport = runRetryVectors(RETRY_VECTORS);
log("hermes retry vectors: " + retryReport.passed + "/" + retryReport.total + " passed, " +
    retryReport.failed + " failed");
for (var r = 0; r < retryReport.failures.length; r++) log("FAIL " + retryReport.failures[r]);
if (retryReport.failed) { throw new Error("retry vectors failed"); }
var andV4Report = runAndV4Vectors(AND_V4_VECTORS);
log("hermes and_v4 vectors: " + andV4Report.passed + "/" + andV4Report.total + " passed, " +
    andV4Report.failed + " failed");
for (var a4 = 0; a4 < andV4Report.failures.length; a4++) log("FAIL " + andV4Report.failures[a4]);
if (andV4Report.failed) { throw new Error("and_v4 vectors failed"); }
var andV5Report = runAndV5Vectors(AND_V5_VECTORS);
log("hermes and_v5 vectors: " + andV5Report.passed + "/" + andV5Report.total + " passed, " +
    andV5Report.failed + " failed");
for (var a5 = 0; a5 < andV5Report.failures.length; a5++) log("FAIL " + andV5Report.failures[a5]);
if (andV5Report.failed) { throw new Error("and_v5 vectors failed"); }
var gateReport = runGateVectors(GATE_VECTORS);
log("hermes gate vectors: " + gateReport.passed + "/" + gateReport.total + " passed, " +
    gateReport.failed + " failed");
for (var gv = 0; gv < gateReport.failures.length; gv++) log("FAIL " + gateReport.failures[gv]);
if (gateReport.failed) { throw new Error("gate vectors failed"); }
var windowReport = runWindowVectors(WINDOW_VECTORS);
log("hermes window vectors: " + windowReport.passed + "/" + windowReport.total + " passed, " +
    windowReport.failed + " failed");
for (var wv = 0; wv < windowReport.failures.length; wv++) log("FAIL " + windowReport.failures[wv]);
if (windowReport.failed) { throw new Error("window vectors failed"); }
var stripNfReport = runStripNfVectors(STRIP_NF_VECTORS);
log("hermes strip_nf vectors: " + stripNfReport.passed + "/" + stripNfReport.total + " passed, " +
    stripNfReport.failed + " failed");
for (var sn = 0; sn < stripNfReport.failures.length; sn++) log("FAIL " + stripNfReport.failures[sn]);
if (stripNfReport.failed) { throw new Error("strip_nf vectors failed"); }
var fallbackReport = runFallbackVectors(FALLBACK_VECTORS);
log("hermes window_v1 fallback vectors: " + fallbackReport.passed + "/" + fallbackReport.total + " passed, " +
    fallbackReport.failed + " failed");
for (var fb = 0; fb < fallbackReport.failures.length; fb++) log("FAIL " + fallbackReport.failures[fb]);
if (fallbackReport.failed) { throw new Error("window_v1 fallback vectors failed"); }
var contradictionReport = runContradictionVectors(CONTRADICTION_VECTORS);
log("hermes contradiction vectors: " + contradictionReport.passed + "/" + contradictionReport.total + " passed, " +
    contradictionReport.failed + " failed");
for (var cv = 0; cv < contradictionReport.failures.length; cv++) log("FAIL " + contradictionReport.failures[cv]);
if (contradictionReport.failed) { throw new Error("contradiction vectors failed"); }
var echoReport = runEchoVectors(ECHO_VECTORS);
log("hermes echo vectors: " + echoReport.passed + "/" + echoReport.total + " passed, " +
    echoReport.failed + " failed");
for (var ev = 0; ev < echoReport.failures.length; ev++) log("FAIL " + echoReport.failures[ev]);
if (echoReport.failed) { throw new Error("echo vectors failed"); }
var pastDateReport = runPastDateVectors(PAST_DATE_VECTORS);
log("hermes past_date vectors: " + pastDateReport.passed + "/" + pastDateReport.total + " passed, " +
    pastDateReport.failed + " failed");
for (var pv = 0; pv < pastDateReport.failures.length; pv++) log("FAIL " + pastDateReport.failures[pv]);
if (pastDateReport.failed) { throw new Error("past_date vectors failed"); }
var extractReport = runExtractVectors(EXTRACT_VECTORS);
log("hermes extract vectors: " + extractReport.passed + "/" + extractReport.total + " passed, " +
    extractReport.failed + " failed");
for (var xv = 0; xv < extractReport.failures.length; xv++) log("FAIL " + extractReport.failures[xv]);
if (extractReport.failed) { throw new Error("extract vectors failed"); }
var answerV5Report = runAnswerV5Vectors(ANSWER_V5_VECTORS);
log("hermes answer_v5 vectors: " + answerV5Report.passed + "/" + answerV5Report.total + " passed, " +
    answerV5Report.failed + " failed");
for (var a5v = 0; a5v < answerV5Report.failures.length; a5v++) log("FAIL " + answerV5Report.failures[a5v]);
if (answerV5Report.failed) { throw new Error("answer_v5 vectors failed"); }

var flowVector = VECTORS.flow[0];
askAssistant(flowVector.question, {
  nowMs: function () { return flowVector.now_ms; },
  complete: function (call) {
    return Promise.resolve({ text: call.kind === "query" ? flowVector.query_reply : flowVector.answer_reply });
  },
  search: function () { return Promise.resolve(flowVector.search_reply); },
  countTokens: function () { return Promise.resolve(flowVector.case_tokens); },
}).then(function (result) {
  var ok = result.path === flowVector.expected.path && result.text === flowVector.expected.text;
  log("hermes askAssistant " + flowVector.id + ": " + result.path + (ok ? " (as expected)" : " (WRONG)"));
  if (!ok) { throw new Error("askAssistant differs"); }
});

// A question asked during priming (plan "model queue and speed recovery",
// 2026-11-10): the real createAssistantRuntime with a fake llama.rn adapter
// that rejects a second completion while one runs, and promise gates.
var answerVector = null;
for (var k = 0; k < VECTORS.flow.length; k++) if (VECTORS.flow[k].id === "answer") answerVector = VECTORS.flow[k];
var gates = [];
var gateResolvers = [];
for (var g = 0; g < 2; g++) {
  gates.push(new Promise(function (resolve) { gateResolvers.push(resolve); }));
}
var files = {};
var running = false;
var collisions = 0;
var callLog = [];
var gateIndex = 0;
var fakeLlama = {
  countTokens: function (text) { return Promise.resolve(Math.ceil(text.length / 4)); },
  completion: function (prompt, nPredict, measure) {
    if (running) { collisions++; return Promise.reject(new Error("Context is busy")); }
    running = true;
    var kind = prompt.indexOf("You turn a student") !== -1 ? "query" : "answer";
    callLog.push(kind + " " + nPredict);
    var gate = gateIndex < gates.length ? gates[gateIndex++] : Promise.resolve();
    return gate.then(function () {
      running = false;
      var priming = nPredict === 1 || !!measure;
      return {
        text: priming ? "x" : (kind === "query" ? answerVector.query_reply : answerVector.answer_reply),
        timings: { prompt_n: Math.ceil(prompt.length / 4), prompt_per_second: 500,
                   predicted_n: measure ? 16 : (priming ? 1 : 20), predicted_per_second: 500 },
      };
    });
  },
  saveSession: function (path, n) { files[path] = n; return Promise.resolve(n); },
  loadSession: function (path) { return Promise.resolve(files[path]); },
  fileExists: function (path) { return Promise.resolve(Object.prototype.hasOwnProperty.call(files, path)); },
};
var runtime = createAssistantRuntime({
  llama: fakeLlama,
  settings: { dir: "/d", modelSha256: "0123456789abcdef", llamaRnVersion: "0.13.0-rc.8", nCtx: 2048, nThreads: 4 },
});
var priming = runtime.prime(answerVector.now_ms);
var asked = runtime.ask(answerVector.question, {
  nowMs: function () { return answerVector.now_ms; },
  search: function () { return Promise.resolve(answerVector.search_reply); },
});
var stateDuring = runtime.state();
function settle(n) {
  var p = Promise.resolve();
  for (var r = 0; r < n; r++) p = p.then(function () { return undefined; });
  return p;
}
settle(30).then(function () {
  var callsBefore = callLog.join(",");
  gateResolvers[0]();
  gateResolvers[1]();
  return priming.then(function () { return asked; }).then(function (result) {
    var ok = stateDuring === "priming" && callsBefore === "answer 1" && collisions === 0 &&
      result.path === "answer" && callLog.join(",") === "answer 1,query 16,query 64,answer 200" &&
      result.budget !== null && result.budget.rule === "time";
    log("hermes runtime question during priming: " + result.path + " rule " + (result.budget ? result.budget.rule : "none") + " calls [" + callLog.join(", ") + "]" +
        (ok ? " (as expected)" : " (WRONG: state " + stateDuring + ", before [" + callsBefore + "], collisions " + collisions + ")"));
    if (!ok) { throw new Error("runtime differs"); }
  });
});
`;

// Top-level names must be unique in the plain-script bundle (one shared
// scope): a later file would silently replace an earlier one's binding.
// Identical constants generated into two files are allowed.
const ALLOWED_SAME = ["FALLBACK_HEADER", "LAST_RESORT_MESSAGE", "TITLE_MAX_CHARS"];
const BUNDLE_FILES = [
  ["guard-ts", "src", "spec.js"],
  ["guard-ts", "src", "guard.js"],
  ["assistant-ts", "src", "generated.js"],
  ["assistant-ts", "src", "text.js"],
  ["assistant-ts", "src", "render.js"],
  ["assistant-ts", "src", "contract.js"],
  ["assistant-ts", "src", "budget.js"],
  ["assistant-ts", "src", "flow.js"],
  ["assistant-ts", "src", "session.js"],
  ["assistant-ts", "src", "queue.js"],
  ["assistant-ts", "src", "runtime.js"],
  ["assistant-ts", "src", "vectors.js"],
  ["assistant-ts", "src", "searchData.js"],
  ["assistant-ts", "src", "plaintext.js"],
  ["assistant-ts", "src", "search.js"],
  ["assistant-ts", "src", "feed.js"],
  ["assistant-ts", "src", "feedVectors.js"],
  ["assistant-ts", "src", "rank.js"],
  ["assistant-ts", "src", "rankVectors.js"],
  ["assistant-ts", "src", "retry.js"],
  ["assistant-ts", "src", "retryVectors.js"],
  ["assistant-ts", "src", "andV4Vectors.js"],
  ["assistant-ts", "src", "andV5Vectors.js"],
  ["assistant-ts", "src", "gateVectors.js"],
  ["assistant-ts", "src", "window.js"],
  ["assistant-ts", "src", "windowVectors.js"],
  ["assistant-ts", "src", "stripNfVectors.js"],
  ["assistant-ts", "src", "fallback.js"],
  ["assistant-ts", "src", "fallbackVectors.js"],
  ["assistant-ts", "src", "contradiction.js"],
  ["assistant-ts", "src", "contradictionVectors.js"],
  ["assistant-ts", "src", "echo.js"],
  ["assistant-ts", "src", "echoVectors.js"],
  ["assistant-ts", "src", "pastDate.js"],
  ["assistant-ts", "src", "pastDateVectors.js"],
  ["assistant-ts", "src", "extract.js"],
  ["assistant-ts", "src", "extractVectors.js"],
  ["assistant-ts", "src", "answerV5Vectors.js"],
];
const declared = {};
for (const parts of BUNDLE_FILES) {
  const text = plainScript(...parts);
  for (const m of text.matchAll(/^(?:const|let|var|function|class) ([A-Za-z_$][\w$]*)/gm)) {
    if (declared[m[1]] && ALLOWED_SAME.indexOf(m[1]) === -1) {
      console.error("bundle name clash: " + m[1] + " in " + declared[m[1]] + " and " + parts[2]);
      process.exit(2);
    }
    declared[m[1]] = parts[2];
  }
}

const bundle = [
  "// Generated by scripts/hermes-vectors.mjs; do not edit.",
  ...BUNDLE_FILES.map((parts) => plainScript(...parts)),
  "var VECTORS = " + readFileSync(vectorsPath, "utf8").trim() + ";",
  "var FEED_VECTORS = " + readFileSync(feedVectorsPath, "utf8").trim() + ";",
  "var RANK_VECTORS = " + readFileSync(rankVectorsPath, "utf8").trim() + ";",
  "var RETRY_VECTORS = " + readFileSync(retryVectorsPath, "utf8").trim() + ";",
  "var AND_V4_VECTORS = " + readFileSync(andV4VectorsPath, "utf8").trim() + ";",
  "var AND_V5_VECTORS = " + readFileSync(andV5VectorsPath, "utf8").trim() + ";",
  "var GATE_VECTORS = " + readFileSync(gateVectorsPath, "utf8").trim() + ";",
  "var WINDOW_VECTORS = " + readFileSync(windowVectorsPath, "utf8").trim() + ";",
  "var STRIP_NF_VECTORS = " + readFileSync(stripNfVectorsPath, "utf8").trim() + ";",
  "var FALLBACK_VECTORS = " + readFileSync(fallbackVectorsPath, "utf8").trim() + ";",
  "var CONTRADICTION_VECTORS = " + readFileSync(contradictionVectorsPath, "utf8").trim() + ";",
  "var ECHO_VECTORS = " + readFileSync(echoVectorsPath, "utf8").trim() + ";",
  "var PAST_DATE_VECTORS = " + readFileSync(pastDateVectorsPath, "utf8").trim() + ";",
  "var EXTRACT_VECTORS = " + readFileSync(extractVectorsPath, "utf8").trim() + ";",
  "var ANSWER_V5_VECTORS = " + readFileSync(answerV5VectorsPath, "utf8").trim() + ";",
  runner,
].join("\n");
mkdirSync(join(root, "dist-hermes"), { recursive: true });
const out = join(root, "dist-hermes", "run-vectors.js");
writeFileSync(out, bundle);

const binaries = {
  win32: ["win64-bin", "hermes.exe"],
  darwin: ["osx-bin", "hermes"],
  linux: ["linux64-bin", "hermes"],
};
const parts = binaries[process.platform];
const hermes = parts && join(root, "node_modules", "hermes-engine-cli", ...parts);
if (!hermes || !existsSync(hermes)) {
  console.error(`No Hermes CLI binary for ${process.platform} (looked for ${hermes}).`);
  process.exit(2);
}
const run = spawnSync(hermes, ["-Xmicrotask-queue", out], { encoding: "utf8" });
process.stdout.write(run.stdout ?? "");
process.stderr.write(run.stderr ?? "");
if (run.status === 0 && !/hermes askAssistant .* \(as expected\)/.test(run.stdout ?? "")) {
  console.error("askAssistant did not finish under Hermes");
  process.exit(1);
}
if (run.status === 0 && !/hermes runtime question during priming: .* \(as expected\)/.test(run.stdout ?? "")) {
  console.error("the runtime scenario did not finish under Hermes");
  process.exit(1);
}
process.exit(run.status ?? 1);
