/** Hand-written mirror of apps/api/schemas/dashboard.py (keep in sync with the API). */
export type Uuid = string
export type Iso = string

export interface User { id: Uuid; name: string | null; email: string; role: string; tenant_id: Uuid }
export interface TokenResponse { access_token: string; token_type: string; user: User }
export interface ApiKeyCreated { id: Uuid; key: string; label: string | null; created_at: Iso }
export interface ApiKeyOut { id: Uuid; label: string | null; masked_key: string; created_at: Iso; revoked: boolean }

export interface PlatformSummary {
  total_agents: number
  runs_last_7d: number
  gate_pass_rate: number | null
  healthy_budget_count: number
  total_budget_count: number
}

export interface GateResult { passed: boolean; reasons: string[] }
export type BudgetStatus = 'healthy' | 'at_risk' | 'frozen'
export interface ErrorBudget {
  status: BudgetStatus
  window: number
  runs_considered: number
  above_target: number
  breached: number
  allowed_breaches: number
  exhausted: boolean
  target: number
}

export interface AgentLatestRun { id: Uuid; status: string; gate_passed: boolean | null; created_at: Iso }
export interface AgentListItem {
  id: Uuid
  name: string
  description: string | null
  latest_version_label: string | null
  latest_run: AgentLatestRun | null
  latest_ars: number | null
  error_budget_status: BudgetStatus
  created_at: Iso
}

export interface VersionOut { id: Uuid; version_label: string; model_name: string; content_hash: string; entrypoint: string; created_at: Iso }
export interface SuiteOut { id: Uuid; agent_id: Uuid; name: string; case_count: number }

export interface RunListItem {
  id: Uuid
  agent_id: Uuid
  agent_name: string
  version_label: string
  suite_name: string
  status: string
  triggered_by: string
  gate_passed: boolean | null
  ars: number | null
  created_at: Iso
  completed_at: Iso | null
}

export interface ARSPoint {
  eval_run_id: Uuid
  version_label: string
  ars: number
  correctness: number
  safety: number
  latency: number
  cost: number
  created_at: Iso
}

export interface DriftAlert {
  id: Uuid
  agent_id: Uuid
  agent_name: string | null
  drift_type: 'model' | 'prompt' | 'metric'
  metric: string
  baseline_value: number
  current_value: number
  message: string
  eval_run_id: Uuid | null
  diff_run_id: Uuid | null
  detected_at: Iso
}

export interface LatencyBucket { t: number; p95_ms: number; rps: number }
export interface LoadRun {
  id: Uuid
  agent_id: Uuid
  agent_name: string
  status: string
  concurrency: number
  duration_seconds: number
  p50_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
  error_rate: number | null
  throughput_rps: number | null
  cost_per_hour_usd: number | null
  total_requests: number | null
  latency_series: LatencyBucket[] | null
  created_at: Iso
}

export type DiffClass = 'silent_drift' | 'safe_refactor' | 'expected_change' | 'no_op'
export interface DiffRun {
  id: Uuid
  agent_id: Uuid
  agent_name: string
  version_a_label: string
  version_b_label: string
  status: string
  classification: DiffClass | null
  mean_similarity: number | null
  threshold: number
  code_changed: boolean | null
  created_at: Iso
}
export interface DiffCase {
  case_key: string
  description: string | null
  similarity: number
  output_a: string
  output_b: string
  passed_a: boolean
  passed_b: boolean
}
export interface DiffDetail extends DiffRun { cases: DiffCase[] }

export interface AgentDetail {
  id: Uuid
  name: string
  description: string | null
  created_at: Iso
  latest_version: VersionOut | null
  versions: VersionOut[]
  suites: SuiteOut[]
  recent_runs: RunListItem[]
  latest_ars: number | null
  latest_gate: GateResult | null
  error_budget: ErrorBudget
  drift_alerts: DriftAlert[]
  load_runs: LoadRun[]
}

export interface TranscriptTurn {
  role: 'user' | 'assistant'
  content: string
  tool_calls: { name: string; arguments: Record<string, unknown>; result: unknown; latency_ms: number }[] | null
  latency_ms: number | null
  cost_usd: number | null
}
export interface ScorerResult { passed: boolean; detail: string }
export interface CaseResult {
  id: Uuid
  case_key: string
  description: string | null
  is_chaos: boolean
  passed: boolean
  metrics: { cost_usd?: number; latency_ms?: number }
  transcript: TranscriptTurn[]
  scorer_results: Record<string, ScorerResult>
}
export interface ARSBreakdown { ars: number; correctness: number; safety: number; latency: number; cost: number }
export interface RunDetail {
  id: Uuid
  status: string
  triggered_by: string
  agent_id: Uuid
  agent_name: string
  version_label: string
  suite_name: string
  started_at: Iso | null
  completed_at: Iso | null
  created_at: Iso
  gate_result: GateResult | null
  ars: ARSBreakdown | null
  cases: CaseResult[]
}

export interface TraceEvent {
  case_key: string
  turn: number
  kind: 'user' | 'assistant' | 'tool'
  name: string | null
  content: string
  latency_ms: number | null
  cost_usd: number | null
  passed: boolean | null
}

export interface FailureCluster {
  id: Uuid
  cluster_index: number
  label: string
  representative: string
  case_count: number
  bad_outcome_rate: number
  dismissed: boolean
  created_at: Iso
}
export interface Candidate { id: Uuid; case_key: string; prompt: string; status: string; created_at: Iso }
