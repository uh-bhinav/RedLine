// Thin re-exports of the generated OpenAPI schema types, so page/hook files
// import `MeResponse` etc. directly instead of repeating
// `components["schemas"]["MeResponse"]` everywhere.
//
// The generated file (api-types.ts) lags the backend's additive fields, so the
// types below that the dashboard v3 consumes are the generated type
// intersected with / replaced by the shapes in apps/api/schemas/*.py.
import type { components } from "./api-types";

type Schemas = components["schemas"];

export type MeResponse = Schemas["MeResponse"];
export type AgentVersionSummary = Schemas["AgentVersionSummary"];
export type EvalRunSummary = Schemas["EvalRunSummary"];
export type CaseResultItem = Schemas["CaseResultItem"];
export type GateResult = Schemas["GateResult"];
export type ArsSnapshotItem = Schemas["ArsSnapshotItem"];
export type ErrorBudgetResponse = Schemas["ErrorBudgetResponse"];
export type DriftAlertItem = Schemas["DriftAlertItem"];
export type LoadRunSummary = Schemas["LoadRunSummary"];
export type TraceEventItem = Schemas["TraceEventItem"];
export type DiffRunCreate = Schemas["DiffRunCreate"];
export type LoadRunCreate = Schemas["LoadRunCreate"];
export type EvalRunCreate = Schemas["EvalRunCreate"];
export type EvalSuiteSummary = Schemas["EvalSuiteSummary"];
export type CandidateCaseResponse = Schemas["CandidateCaseResponse"];
export type AgentDetailResponse = Schemas["AgentDetailResponse"];

export type Role = "admin" | "developer" | "viewer";

// ---- additive backend fields (apps/api/schemas/dashboard.py) ----

/** GET /dashboard/agents item; `latest_ars` = latest ARS across all versions (null = never scored). */
export type AgentListItem = Schemas["AgentListItem"] & { latest_ars?: number | null };

/** GET /dashboard/summary */
export interface PlatformSummary {
  total_agents: number;
  runs_last_7d: number;
  /** 0..1, or null when there are no completed runs. */
  gate_pass_rate: number | null;
  healthy_budget_count: number;
  total_budget_count: number;
}

export interface ArsBreakdown {
  ars: number;
  correctness: number;
  safety: number;
  latency: number;
  cost: number;
}

/** GET /dashboard/runs/{id} -- generated type plus run-context + ARS fields. */
export type RunDetailResponse = Schemas["RunDetailResponse"] & {
  agent_id?: string | null;
  agent_name?: string | null;
  agent_version_id?: string | null;
  version_label?: string | null;
  suite_id?: string | null;
  suite_name?: string | null;
  created_at?: string | null;
  ars?: ArsBreakdown | null;
};

/** GET /dashboard/runs item (cross-agent). */
export interface RunListItem {
  id: string;
  agent_id: string;
  agent_name: string;
  agent_version_id: string;
  version_label: string;
  suite_id: string;
  suite_name: string | null;
  status: string;
  triggered_by: string;
  gate_passed: boolean | null;
  ars: number | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/** GET /dashboard/diffs item (cross-agent). */
export interface DiffListItem {
  id: string;
  agent_id: string;
  agent_name: string;
  version_a_id: string;
  version_b_id: string;
  version_a_label: string | null;
  version_b_label: string | null;
  suite_id: string;
  suite_name: string | null;
  classification: string;
  code_changed: boolean;
  behavior_changed: boolean;
  mean_similarity: number;
  threshold: number;
  eval_run_a_id: string;
  eval_run_b_id: string;
  created_at: string;
}

/** GET /dashboard/load-runs item (cross-agent). */
export interface LoadRunListItem {
  id: string;
  agent_id: string;
  agent_name: string;
  agent_version_id: string;
  version_label: string;
  status: string;
  triggered_by: string;
  concurrency: number;
  duration_seconds: number;
  total_requests: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
  error_rate: number | null;
  throughput_rps: number | null;
  cost_per_hour_usd: number | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/** GET /diff-runs/{id} with additive context fields. */
export type DiffRunResponse = Schemas["DiffRunResponse"] & {
  agent_id?: string | null;
  agent_name?: string | null;
  version_a_id?: string | null;
  version_b_id?: string | null;
  version_a_label?: string | null;
  version_b_label?: string | null;
  suite_id?: string | null;
  suite_name?: string | null;
  created_at?: string | null;
};

/** GET /load-runs/{id} (generated shape; fields documented in schemas/load_run.py). */
export type LoadRunResponse = Schemas["LoadRunResponse"];

/** GET /mining/{agent_id}/clusters and POST /mining/{agent_id}/run items. */
export interface FailureClusterResponse {
  id: string;
  cluster_label: number;
  size: number;
  bad_outcome_rate: number;
  representative_text: string;
  created_at: string;
}

// ---- API keys (apps/api/routers/auth.py) ----
export interface ApiKeyItem {
  id: string;
  label: string;
  role: string;
  masked_key: string;
  key_prefix: string | null;
  last_four: string | null;
  created_at: string;
  revoked: boolean;
  revoked_at: string | null;
}
/** Returned once on creation: carries the raw `key`. */
export interface ApiKeyCreated extends ApiKeyItem {
  key: string;
}
export interface ApiKeyCreate {
  label: string;
  role?: Role;
}

// ---- agent registration (POST /agents, POST /agents/{id}/versions) ----
export interface AgentCreate {
  name: string;
  description?: string | null;
}
export interface AgentResponse {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}
export interface AgentVersionCreate {
  version_label: string;
  model_name: string;
  prompt_text: string;
  tool_schema?: Record<string, unknown>[];
  content_hash: string;
  entrypoint: string;
  git_commit_sha?: string | null;
}
export interface AgentVersionResponse {
  id: string;
  agent_id: string;
  version_label: string;
  model_name: string;
  content_hash: string;
  entrypoint: string;
  created_at: string;
}

// The generated type for CaseResultItem.transcript is a loose
// Record<string, unknown>[] (Pydantic `list[dict]` on the wire) -- this
// reflects the actual shape from apps/api/services/scorers/base.py's Turn
// model, which is what the backend serializes into each element.
export interface TranscriptTurn {
  role: "user" | "assistant";
  content: string;
  tool_calls?: { name: string; arguments?: Record<string, unknown>; result?: unknown }[] | null;
  latency_ms?: number | null;
  cost_usd?: number | null;
}
