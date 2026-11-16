import { Activity, Bot, PlayCircle, ShieldCheck } from 'lucide-react'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertStrip, ErrorCard, SummaryCard, type StripAlert } from '@/components/shared'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { useAgents, useDiffs, usePlatformSummary } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useAuth } from '@/lib/auth'
import { formatAr, greeting } from '@/lib/utils'
import { AgentsEmptyState, AgentsTable } from '@/pages/AgentsListPage'

export default function DashboardPage() {
  useDocumentTitle('Dashboard')
  const { user } = useAuth()
  const navigate = useNavigate()
  const summary = usePlatformSummary()
  const agents = useAgents()
  const diffs = useDiffs()

  // Alerts are derived client-side from data we already fetched -- no extra endpoint.
  const alerts = useMemo<StripAlert[]>(() => {
    const out: StripAlert[] = []
    for (const a of agents.data ?? []) {
      if (a.error_budget_status === 'frozen')
        out.push({ id: `budget-${a.id}`, tone: 'bad', href: `/agent/${a.id}`, message: `${a.name} — Error budget exhausted, deployments frozen` })
      else if (a.latest_ars != null && a.latest_ars < 0.9)
        out.push({ id: `ars-${a.id}`, tone: 'warn', href: `/agent/${a.id}`, message: `${a.name} — ARS ${formatAr(a.latest_ars)} is below the 0.9 target` })
      else if (a.latest_run?.gate_passed === false)
        out.push({ id: `gate-${a.id}`, tone: 'warn', href: `/agent/${a.id}`, message: `${a.name} — latest gate check failed` })
    }
    for (const d of diffs.data ?? [])
      if (d.classification === 'silent_drift')
        out.push({ id: `drift-${d.id}`, tone: 'bad', href: `/diffs/${d.id}`, message: `${d.agent_name} — SILENT_DRIFT detected (similarity ${d.mean_similarity?.toFixed(2)})` })
    return out.sort((a, b) => (a.tone === b.tone ? 0 : a.tone === 'bad' ? -1 : 1))
  }, [agents.data, diffs.data])

  const s = summary.data
  const passTone = s?.gate_pass_rate == null ? 'default' : s.gate_pass_rate >= 0.7 ? 'good' : s.gate_pass_rate >= 0.5 ? 'warn' : 'bad'
  const budgetTone = !s ? 'default' : s.healthy_budget_count === s.total_budget_count ? 'good' : s.healthy_budget_count === 0 ? 'bad' : 'warn'

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">{greeting()}, {user?.name?.split(' ')[0] ?? 'there'}</h1>
        <p className="text-muted-foreground">Here's your platform health · {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}</p>
      </div>

      {summary.error ? <ErrorCard error={summary.error} onRetry={() => summary.refetch()} /> : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {!s ? [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />) : (
            <>
              <SummaryCard index={0} icon={Bot} label="Total Agents" value={s.total_agents} />
              <SummaryCard index={1} icon={PlayCircle} label="Runs (7 days)" value={s.runs_last_7d} />
              <SummaryCard index={2} icon={ShieldCheck} label="Gate Pass Rate" tone={passTone}
                {...(s.gate_pass_rate == null ? { text: 'No runs yet' } : { value: s.gate_pass_rate * 100, suffix: '%', decimals: 0 })} />
              <SummaryCard index={3} icon={Activity} label="Budgets Healthy" tone={budgetTone} text={`${s.healthy_budget_count}/${s.total_budget_count}`} />
            </>
          )}
        </div>
      )}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Active alerts</h2>
        {agents.isLoading ? <Skeleton className="h-14" /> : <AlertStrip alerts={alerts} onView={(href) => navigate(href)} />}
      </section>

      <Card>
        <CardHeader><CardTitle>Agents</CardTitle></CardHeader>
        {agents.isLoading ? <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
          : agents.error ? <div className="p-5"><ErrorCard error={agents.error} onRetry={() => agents.refetch()} /></div>
          : !agents.data?.length ? <AgentsEmptyState />
          : <AgentsTable agents={agents.data} />}
      </Card>
    </div>
  )
}
