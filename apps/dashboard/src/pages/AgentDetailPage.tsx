import { GitCompare, PlayCircle, Zap } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { ArsTrendChart, DriftAlertsList, FailureClustersPanel } from '@/components/analytics'
import { TriggerDiffRunDialog, TriggerEvalRunDialog, TriggerLoadRunDialog } from '@/components/dialogs'
import { ARSRing, EmptyState, ErrorBudgetGauge, ErrorCard, GateBadge } from '@/components/shared'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge, Skeleton } from '@/components/ui/misc'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/overlay'
import { useAgent, useArsHistory } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import type { AgentDetail, LoadRun } from '@/lib/types'
import { arsColor, cn, formatAr, formatDateTime, shortId, timeAgo } from '@/lib/utils'

function HealthCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2 p-5">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      {children}
    </div>
  )
}

function AgentHealthHeader({ agent }: { agent: AgentDetail }) {
  const latestAlert = agent.drift_alerts[0]
  const gate = agent.latest_gate
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 p-5">
        <div>
          <div className="flex items-center gap-2"><h1 className="text-2xl font-bold">{agent.name}</h1>
            {agent.latest_version && <Badge variant="outline">{agent.latest_version.version_label} · {agent.latest_version.model_name}</Badge>}</div>
          <p className="text-sm text-muted-foreground">{agent.description ?? 'No description'}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <TriggerDiffRunDialog agent={agent}><Button variant="outline"><GitCompare />Diff</Button></TriggerDiffRunDialog>
          <TriggerLoadRunDialog agent={agent}><Button variant="outline"><Zap />Load</Button></TriggerLoadRunDialog>
          <TriggerEvalRunDialog agent={agent}><Button variant="brand"><PlayCircle />Run Eval</Button></TriggerEvalRunDialog>
        </div>
      </div>
      <div className="grid grid-cols-2 divide-x divide-y border-t lg:grid-cols-4 lg:divide-y-0">
        <HealthCell label="ARS Score">
          <div className="flex items-center gap-3">
            <ARSRing ars={agent.latest_ars} />
            <span className={cn('text-sm font-semibold', arsColor(agent.latest_ars))}>
              {agent.latest_ars == null ? 'No score yet' : agent.latest_ars >= 0.9 ? 'Healthy' : agent.latest_ars >= 0.7 ? 'At risk' : 'Critical'}
            </span>
          </div>
        </HealthCell>
        <HealthCell label="Error Budget"><ErrorBudgetGauge budget={agent.error_budget} /></HealthCell>
        <HealthCell label="Drift Status">
          {latestAlert ? (
            <div className="space-y-1.5">
              <Badge variant="fail" className="px-3 py-1 text-sm">ALERT</Badge>
              <p className="text-sm text-muted-foreground capitalize">{agent.drift_alerts.length} {latestAlert.drift_type} drift alert{agent.drift_alerts.length > 1 ? 's' : ''}</p>
              <Button asChild variant="link" size="sm" className="h-auto p-0">
                <Link to={latestAlert.diff_run_id ? `/diffs/${latestAlert.diff_run_id}` : latestAlert.eval_run_id ? `/runs/${latestAlert.eval_run_id}` : '#'}>Investigate →</Link>
              </Button>
            </div>
          ) : (
            <div className="space-y-1.5"><Badge variant="pass" className="px-3 py-1 text-sm">CLEAN</Badge><p className="text-sm text-muted-foreground">No drift detected</p></div>
          )}
        </HealthCell>
        <HealthCell label="Gate">
          <div className="space-y-1.5">
            <div className="origin-left scale-125"><GateBadge passed={gate?.passed} /></div>
            <p className="pt-1 text-sm text-muted-foreground">{gate ? (gate.passed ? 'All thresholds met' : `${gate.reasons.length} rule${gate.reasons.length > 1 ? 's' : ''} violated`) : 'No completed run'}</p>
          </div>
        </HealthCell>
      </div>
    </Card>
  )
}

function LoadSummary({ load }: { load: LoadRun }) {
  const errOk = (load.error_rate ?? 0) <= 0.01
  return (
    <Card className="p-5">
      <div className="text-sm text-muted-foreground">Latest load test ({timeAgo(load.created_at)}) · {load.concurrency} concurrent users · {load.duration_seconds} seconds</div>
      <div className="mt-2 flex flex-wrap gap-x-8 gap-y-1 font-mono text-sm">
        <span>p95: <b>{load.p95_ms}ms</b></span>
        <span>Error rate: <b className={errOk ? '' : 'text-amber-600'}>{((load.error_rate ?? 0) * 100).toFixed(1)}%</b></span>
        <span>Cost/hour: <b>${load.cost_per_hour_usd?.toFixed(2)}</b></span>
        <span>Throughput: <b>{load.throughput_rps} req/s</b></span>
      </div>
      <p className={cn('mt-2 text-sm font-medium', (load.cost_per_hour_usd ?? 0) * 10 <= 10 ? 'text-green-600 dark:text-green-400' : 'text-amber-600')}>
        ● {(load.cost_per_hour_usd ?? 0) * 10 <= 10 ? 'Financially viable at current scale' : 'Review before scaling'}
      </p>
    </Card>
  )
}

export default function AgentDetailPage() {
  const { id = '' } = useParams()
  const { data: agent, isLoading, error, refetch } = useAgent(id)
  const ars = useArsHistory(id)
  useDocumentTitle(agent?.name ?? 'Agent')

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-56" /><Skeleton className="h-96" /></div>
  if (error || !agent) return <ErrorCard error={error ?? new Error('Agent not found')} onRetry={() => refetch()} />

  return (
    <div className="space-y-6">
      <AgentHealthHeader agent={agent} />
      <Tabs defaultValue="runs">
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="runs">Recent Runs</TabsTrigger>
          <TabsTrigger value="trend">ARS Trend</TabsTrigger>
          <TabsTrigger value="drift">Drift Alerts{agent.drift_alerts.length > 0 && <Badge variant="fail" className="ml-1 px-1.5 py-0">{agent.drift_alerts.length}</Badge>}</TabsTrigger>
          <TabsTrigger value="clusters">Failure Clusters</TabsTrigger>
          <TabsTrigger value="load">Load Tests</TabsTrigger>
        </TabsList>

        <TabsContent value="runs">
          <Card>
            {agent.recent_runs.length === 0 ? (
              <EmptyState icon={PlayCircle} title="No eval runs yet" description="Run your suite to get the first reliability score."
                action={<TriggerEvalRunDialog agent={agent}><Button variant="brand">Trigger Eval Run</Button></TriggerEvalRunDialog>} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] text-sm">
                  <thead><tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    {['Run', 'Version', 'Suite', 'Gate', 'ARS', 'Trigger', 'When'].map((h) => <th key={h} className="px-4 py-3 font-medium">{h}</th>)}</tr></thead>
                  <tbody>
                    {agent.recent_runs.map((r) => (
                      <tr key={r.id} className="border-b last:border-0 hover:bg-muted/50">
                        <td className="px-4 py-3"><Link to={`/runs/${r.id}`} className="font-mono text-brand hover:underline">{shortId(r.id)}</Link></td>
                        <td className="px-4 py-3"><Badge variant="outline">{r.version_label}</Badge></td>
                        <td className="px-4 py-3">{r.suite_name}</td>
                        <td className="px-4 py-3"><GateBadge passed={r.gate_passed} status={r.status} /></td>
                        <td className={cn('px-4 py-3 font-mono font-semibold', arsColor(r.ars))}>{formatAr(r.ars)}</td>
                        <td className="px-4 py-3 capitalize text-muted-foreground">{r.triggered_by}</td>
                        <td className="px-4 py-3 text-muted-foreground" title={formatDateTime(r.created_at)}>{timeAgo(r.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="trend">
          <Card>
            <CardHeader><CardTitle>Reliability score over time</CardTitle></CardHeader>
            <CardContent>
              {ars.isLoading ? <Skeleton className="h-96" /> : ars.error ? <ErrorCard error={ars.error} onRetry={() => ars.refetch()} /> : <ArsTrendChart points={ars.data ?? []} />}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="drift"><DriftAlertsList alerts={agent.drift_alerts} /></TabsContent>
        <TabsContent value="clusters"><FailureClustersPanel agentId={agent.id} /></TabsContent>

        <TabsContent value="load" className="space-y-4">
          {agent.load_runs.length === 0 ? (
            <Card><EmptyState icon={Zap} title="No load tests yet" description="Simulate concurrent users to see latency, error rate and cost at scale."
              action={<TriggerLoadRunDialog agent={agent}><Button variant="brand">Run Load Test</Button></TriggerLoadRunDialog>} /></Card>
          ) : (
            <>
              <LoadSummary load={agent.load_runs[0]} />
              <Card className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <thead><tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    {['Run', 'Users', 'p95', 'Error rate', 'Cost/hr', 'Status', 'When'].map((h) => <th key={h} className="px-4 py-3 font-medium">{h}</th>)}</tr></thead>
                  <tbody>
                    {agent.load_runs.map((l) => (
                      <tr key={l.id} className="border-b last:border-0 hover:bg-muted/50">
                        <td className="px-4 py-3"><Link to={`/load-run/${l.id}`} className="font-mono text-brand hover:underline">{shortId(l.id)}</Link></td>
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
              </Card>
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
