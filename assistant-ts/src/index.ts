// The assistant-ts public API. See README.md.
export { askAssistant, startQuestion } from "./flow.ts";
export type {
  AssistantDeps,
  AssistantResult,
  Completion,
  ModelCall,
  Outcome,
  Path,
  QuestionLog,
  Step,
  StepInput,
  Trace,
} from "./flow.ts";
export { decideBudget, predictMs, speedKnown, speedState, updateSpeed } from "./budget.ts";
export type { Budget, BudgetRule, KnownSpeed, Speed, SpeedState } from "./budget.ts";
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
} from "./generated.ts";
