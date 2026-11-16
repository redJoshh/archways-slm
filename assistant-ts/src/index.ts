// The assistant-ts public API. See README.md.
export { answerReplyText, askAssistant, resultsList, startQuestion } from "./flow.ts";
export type {
  AssistantDeps,
  AssistantResult,
  Completion,
  FlowOptions,
  ModelCall,
  Outcome,
  Path,
  QuestionLog,
  Step,
  StepInput,
  StripNf,
  Trace,
} from "./flow.ts";
export {
  answerSpeedSuspect,
  decideBudget,
  predictMs,
  querySpeedState,
  speedKnown,
  speedState,
  updateAnswerSpeed,
  updateSpeed,
} from "./budget.ts";
export type { Budget, BudgetRule, KnownSpeed, Pending, Speed, SpeedState } from "./budget.ts";
export { checkArguments, checkQuestion, checkResults, parseQueryReply } from "./contract.ts";
export type { SearchArguments } from "./contract.ts";
export {
  answerSystem,
  answerUserMessage,
  casePart,
  querySystem,
  QWEN3_STOP,
  renderQwen3,
  systemTurn,
  todayText,
} from "./render.ts";
export type { Announcement } from "./render.ts";
export {
  makeComplete,
  MEASURE_TOKENS,
  N_PREDICT,
  primeOne,
  primeSessions,
  sessionFile,
  sessionPrefix,
  speedFromPriming,
  speedsFromPriming,
} from "./session.ts";
export type { Kind, LlamaAdapter, PrimeReport, SessionSettings } from "./session.ts";
export {
  ANSWER_PROMPT_SHA256,
  BAR_MS,
  BUDGET_CASE_TOKENS,
  GEN_TOKENS,
  LAST_RESORT_MESSAGE,
  NOT_FOUND_MESSAGE,
  QUERY_PROMPT_SHA256,
  QUESTION_MAX_CHARS,
  REMEASURE_MAX_PER_DAY,
  SUSPECT_RATIO,
} from "./generated.ts";
// One serial model queue and the runtime (plan "model queue and speed recovery", 2026-11-10).
export { createModelQueue } from "./queue.ts";
export type { ModelQueue, QueueResult } from "./queue.ts";
export { createAssistantRuntime } from "./runtime.ts";
export type { AssistantRuntime, RuntimeDeps, RuntimeOptions, RuntimeState } from "./runtime.ts";
// On-phone search over the student's feed (ADR 0006).
export { createFeedIndex, HttpError, makeFeedSearch } from "./feedIndex.ts";
export type { FeedIndex, FeedIndexOptions, FetchJson, IndexReport } from "./feedIndex.ts";
export { feedRow, parsePublishedAt } from "./feed.ts";
export type { PublishedAt } from "./feed.ts";
export { cutCodePoints, plainText } from "./plaintext.ts";
export { pluralAlternative, queryGroups, searchRows, wholeWordIn } from "./search.ts";
export type { IndexRow } from "./search.ts";
