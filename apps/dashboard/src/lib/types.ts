// Thin re-exports of the generated OpenAPI schema types, so page/hook files
// import `MeResponse` etc. directly instead of repeating
// `components["schemas"]["MeResponse"]` everywhere.
import type { components } from "./api-types";

type Schemas = components["schemas"];

export type MeResponse = Schemas["MeResponse"];
export type AgentListItem = Schemas["AgentListItem"];
export type AgentDetailResponse = Schemas["AgentDetailResponse"];
export type AgentVersionSummary = Schemas["AgentVersionSummary"];
export type EvalRunSummary = Schemas["EvalRunSummary"];
export type RunDetailResponse = Schemas["RunDetailResponse"];
export type CaseResultItem = Schemas["CaseResultItem"];
export type GateResult = Schemas["GateResult"];
export type ArsSnapshotItem = Schemas["ArsSnapshotItem"];
export type ErrorBudgetResponse = Schemas["ErrorBudgetResponse"];
export type DriftAlertItem = Schemas["DriftAlertItem"];
export type LoadRunSummary = Schemas["LoadRunSummary"];
export type LoadRunResponse = Schemas["LoadRunResponse"];
export type TraceEventItem = Schemas["TraceEventItem"];
export type DiffRunResponse = Schemas["DiffRunResponse"];
export type DiffRunCreate = Schemas["DiffRunCreate"];
export type LoadRunCreate = Schemas["LoadRunCreate"];
export type EvalRunCreate = Schemas["EvalRunCreate"];
export type EvalSuiteSummary = Schemas["EvalSuiteSummary"];
export type FailureClusterResponse = Schemas["FailureClusterResponse"];
export type CandidateCaseResponse = Schemas["CandidateCaseResponse"];

export type Role = "admin" | "developer" | "viewer";

// The generated type for CaseResultItem.transcript is a loose
// Record<string, unknown>[] (Pydantic `list[dict]` on the wire) -- this
// reflects the actual shape from apps/api/services/scorers/base.py's Turn
// model, which is what the backend serializes into each element.
export interface TranscriptTurn {
  role: "user" | "assistant";
  content: string;
  tool_calls?: { name: string; arguments?: Record<string, unknown> }[] | null;
  latency_ms?: number | null;
  cost_usd?: number | null;
}
