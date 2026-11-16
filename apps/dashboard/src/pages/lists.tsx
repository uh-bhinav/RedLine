import { GitCompare, PlayCircle, Zap } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { EmptyState, ErrorCard, GateBadge } from '@/components/shared'
import { Card } from '@/components/ui/card'
import { Badge, Skeleton } from '@/components/ui/misc'
import { useDiffs, useLoadRuns, useRuns } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { arsColor, cn, formatAr, shortId, timeAgo } from '@/lib/utils'
import { CLASSIFICATION } from '@/pages/DiffViewerPage'

function Shell({ title, subtitle, loading, error, retry, empty, children }: {
  title: string; subtitle: string; loading: boolean; error: unknown; retry: () => void; empty?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-bold">{title}</h1><p className="text-sm text-muted-foreground">{subtitle}</p></div>
      <Card className="overflow-x-auto">
        {loading ? <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
          : error ? <div className="p-5"><ErrorCard error={error} onRetry={retry} /></div>
          : empty ?? children}
      </Card>
    </div>
  )
}

const Th = ({ children }: { children: React.ReactNode }) => <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">{children}</th>

export function EvalRunsListPage() {
  useDocumentTitle('Eval Runs')
  const { data, isLoading, error, refetch } = useRuns()
  const navigate = useNavigate()
  return (
    <Shell title="Eval Runs" subtitle="Every evaluation across all agents, newest first." loading={isLoading} error={error} retry={() => refetch()}
      empty={!data?.length ? <EmptyState icon={PlayCircle} title="No eval runs yet" description="Trigger one from an agent page or with `agentbench run`." /> : undefined}>
      <table className="w-full min-w-[760px] text-sm">
        <thead><tr className="border-b"><Th>Run</Th><Th>Agent</Th><Th>Version</Th><Th>Suite</Th><Th>Gate</Th><Th>ARS</Th><Th>Trigger</Th><Th>When</Th></tr></thead>
        <tbody>
          {data?.map((r) => (
            <tr key={r.id} className="cursor-pointer border-b last:border-0 hover:bg-muted/50" onClick={() => navigate(`/runs/${r.id}`)}>
              <td className="px-4 py-3 font-mono text-brand">{shortId(r.id)}</td>
              <td className="px-4 py-3 font-medium">{r.agent_name}</td>
              <td className="px-4 py-3"><Badge variant="outline">{r.version_label}</Badge></td>
              <td className="px-4 py-3">{r.suite_name}</td>
              <td className="px-4 py-3"><GateBadge passed={r.gate_passed} status={r.status} /></td>
              <td className={cn('px-4 py-3 font-mono font-semibold', arsColor(r.ars))}>{formatAr(r.ars)}</td>
              <td className="px-4 py-3 capitalize text-muted-foreground">{r.triggered_by}</td>
              <td className="px-4 py-3 text-muted-foreground">{timeAgo(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  )
}

export function LoadTestsListPage() {
  useDocumentTitle('Load Tests')
  const { data, isLoading, error, refetch } = useLoadRuns()
  const navigate = useNavigate()
  return (
    <Shell title="Load Tests" subtitle="Latency, error rate and cost under concurrent users." loading={isLoading} error={error} retry={() => refetch()}
      empty={!data?.length ? <EmptyState icon={Zap} title="No load tests yet" description="Start one from an agent's Load button." /> : undefined}>
      <table className="w-full min-w-[720px] text-sm">
        <thead><tr className="border-b"><Th>Run</Th><Th>Agent</Th><Th>Users</Th><Th>p95</Th><Th>Error rate</Th><Th>Cost / hr</Th><Th>Status</Th><Th>When</Th></tr></thead>
        <tbody>
          {data?.map((l) => (
            <tr key={l.id} className="cursor-pointer border-b last:border-0 hover:bg-muted/50" onClick={() => navigate(`/load-run/${l.id}`)}>
              <td className="px-4 py-3 font-mono text-brand">{shortId(l.id)}</td>
              <td className="px-4 py-3 font-medium">{l.agent_name}</td>
              <td className="px-4 py-3">{l.concurrency}</td>
              <td className="px-4 py-3 font-mono">{l.p95_ms ?? '—'}ms</td>
              <td className="px-4 py-3 font-mono">{l.error_rate == null ? '—' : `${(l.error_rate * 100).toFixed(1)}%`}</td>
              <td className="px-4 py-3 font-mono">{l.cost_per_hour_usd == null ? '—' : `$${l.cost_per_hour_usd.toFixed(2)}`}</td>
              <td className="px-4 py-3"><Badge variant={l.status === 'completed' ? 'pass' : l.status === 'failed' ? 'fail' : 'warn'}>{l.status}</Badge></td>
              <td className="px-4 py-3 text-muted-foreground">{timeAgo(l.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  )
}

export function DiffsListPage() {
  useDocumentTitle('Diffs')
  const { data, isLoading, error, refetch } = useDiffs()
  return (
    <Shell title="Behavioural Diffs" subtitle="What changed in what agents say — not just in their code." loading={isLoading} error={error} retry={() => refetch()}
      empty={!data?.length ? <EmptyState icon={GitCompare} title="No diffs yet" description="Compare two versions from an agent's Diff button." /> : undefined}>
      <table className="w-full min-w-[720px] text-sm">
        <thead><tr className="border-b"><Th>Diff</Th><Th>Agent</Th><Th>Versions</Th><Th>Classification</Th><Th>Similarity</Th><Th>When</Th></tr></thead>
        <tbody>
          {data?.map((d) => (
            <tr key={d.id} className="border-b last:border-0 hover:bg-muted/50">
              <td className="px-4 py-3"><Link to={`/diffs/${d.id}`} className="font-mono text-brand hover:underline">{shortId(d.id)}</Link></td>
              <td className="px-4 py-3 font-medium">{d.agent_name}</td>
              <td className="px-4 py-3 font-mono text-xs">{d.version_a_label} → {d.version_b_label}</td>
              <td className="px-4 py-3">
                {d.classification ? (
                  <Badge variant={d.classification === 'silent_drift' ? 'fail' : d.classification === 'expected_change' ? 'pass' : d.classification === 'safe_refactor' ? 'info' : 'secondary'}>
                    {CLASSIFICATION[d.classification].title.replace(' DETECTED', '')}
                  </Badge>
                ) : <Badge variant="warn">{d.status}</Badge>}
              </td>
              <td className="px-4 py-3 font-mono">{d.mean_similarity?.toFixed(3) ?? '—'}</td>
              <td className="px-4 py-3 text-muted-foreground">{timeAgo(d.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  )
}
