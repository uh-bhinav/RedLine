import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  AgentDetail, AgentListItem, ApiKeyCreated, ApiKeyOut, ARSPoint, Candidate, DiffDetail, DiffRun,
  DriftAlert, FailureCluster, LoadRun, PlatformSummary, RunDetail, RunListItem, SuiteOut, TraceEvent,
} from '@/lib/types'

const ACTIVE = new Set(['pending', 'running'])

export const usePlatformSummary = () =>
  useQuery({ queryKey: ['summary'], queryFn: () => api<PlatformSummary>('/dashboard/summary'), staleTime: 30_000 })

export const useAgents = () =>
  useQuery({ queryKey: ['agents'], queryFn: () => api<AgentListItem[]>('/dashboard/agents'), staleTime: 15_000 })

export const useAgent = (id: string) =>
  useQuery({
    queryKey: ['agent', id],
    queryFn: () => api<AgentDetail>(`/dashboard/agents/${id}`),
    refetchInterval: (q) => (q.state.data?.recent_runs.some((r) => ACTIVE.has(r.status)) ? 3000 : false),
  })

export const useArsHistory = (id: string) =>
  useQuery({ queryKey: ['ars', id], queryFn: () => api<ARSPoint[]>(`/dashboard/agents/${id}/ars-history`) })

export const useDriftAlerts = (id: string) =>
  useQuery({ queryKey: ['drift', id], queryFn: () => api<DriftAlert[]>(`/dashboard/agents/${id}/drift-alerts`) })

export const useRuns = () =>
  useQuery({
    queryKey: ['runs'],
    queryFn: () => api<RunListItem[]>('/dashboard/runs'),
    refetchInterval: (q) => (q.state.data?.some((r) => ACTIVE.has(r.status)) ? 3000 : false),
  })

export const useRun = (id: string) =>
  useQuery({
    queryKey: ['run', id],
    queryFn: () => api<RunDetail>(`/dashboard/runs/${id}`),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 2000 : false),
  })

export const useTraces = (runId: string) =>
  useQuery({ queryKey: ['traces', runId], queryFn: () => api<TraceEvent[]>(`/dashboard/runs/${runId}/traces`) })

export const useDiffs = () =>
  useQuery({
    queryKey: ['diffs'],
    queryFn: () => api<DiffRun[]>('/diffs'),
    refetchInterval: (q) => (q.state.data?.some((d) => ACTIVE.has(d.status)) ? 3000 : false),
  })

export const useDiff = (id: string) =>
  useQuery({
    queryKey: ['diff', id],
    queryFn: () => api<DiffDetail>(`/diffs/${id}`),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 2000 : false),
  })

export const useLoadRuns = () =>
  useQuery({
    queryKey: ['loads'],
    queryFn: () => api<LoadRun[]>('/load-runs'),
    refetchInterval: (q) => (q.state.data?.some((l) => ACTIVE.has(l.status)) ? 3000 : false),
  })

export const useLoadRun = (id: string) =>
  useQuery({
    queryKey: ['load', id],
    queryFn: () => api<LoadRun>(`/load-runs/${id}`),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 2000 : false),
  })

export const useSuites = (agentId: string) =>
  useQuery({ queryKey: ['suites', agentId], queryFn: () => api<SuiteOut[]>(`/eval-suites?agent_id=${agentId}`) })

export const useClusters = (agentId: string) =>
  useQuery({ queryKey: ['clusters', agentId], queryFn: () => api<FailureCluster[]>(`/mining/${agentId}/clusters`) })

export const useCandidates = (agentId: string) =>
  useQuery({ queryKey: ['candidates', agentId], queryFn: () => api<Candidate[]>(`/mining/${agentId}/candidates`) })

export const useApiKeys = () =>
  useQuery({ queryKey: ['apikeys'], queryFn: () => api<ApiKeyOut[]>('/auth/api-keys') })

// ---------------- mutations ----------------
export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<ApiKeyCreated>('/auth/api-keys', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['apikeys'] }),
  })
}

export function useRevokeApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/auth/api-keys/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['apikeys'] }),
  })
}

export function useCreateEvalRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { agent_version_id: string; suite_id: string }) =>
      api<{ id: string }>('/eval-runs', { method: 'POST', body: { ...p, triggered_by: 'manual' } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent'] })
      qc.invalidateQueries({ queryKey: ['runs'] })
    },
  })
}

export function useCreateDiff() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { agent_id: string; suite_id: string; version_a_id: string; version_b_id: string }) =>
      api<DiffRun>('/diffs', { method: 'POST', body: p }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diffs'] }),
  })
}

export function useCreateLoadRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { agent_version_id: string; suite_id: string; concurrency: number; duration_seconds: number }) =>
      api<LoadRun>('/load-runs', { method: 'POST', body: p }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['loads'] })
      qc.invalidateQueries({ queryKey: ['agent'] })
    },
  })
}

export function useRunMining(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<FailureCluster[]>(`/mining/${agentId}/run`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters', agentId] })
      qc.invalidateQueries({ queryKey: ['candidates', agentId] })
    },
  })
}

export function useDismissCluster(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>(`/mining/clusters/${id}/dismiss`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clusters', agentId] }),
  })
}

export function useReviewCandidate(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: { id: string; decision: 'approve' | 'reject' }) =>
      api<Candidate>(`/mining/candidates/${p.id}/review`, { method: 'POST', body: { decision: p.decision } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['candidates', agentId] }),
  })
}

export function useRegisterAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (p: { name: string; description?: string; entrypoint: string }) => {
      const agent = await api<{ id: string }>('/agents', { method: 'POST', body: { name: p.name, description: p.description || null } })
      // The browser can't hash agent source, so derive a stable id from the entrypoint + time.
      const bytes = new TextEncoder().encode(`${p.entrypoint}:${Date.now()}`)
      const digest = await crypto.subtle.digest('SHA-256', bytes)
      const content_hash = Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('')
      await api(`/agents/${agent.id}/versions`, {
        method: 'POST',
        body: { version_label: 'v1', model_name: 'unspecified', prompt_text: '(registered from dashboard)', content_hash, entrypoint: p.entrypoint },
      })
      return agent
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
    },
  })
}
