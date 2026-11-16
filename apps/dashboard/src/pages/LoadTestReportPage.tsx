import { Loader2 } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { CostViabilityCard, LatencyChart } from '@/components/analytics'
import { ErrorCard } from '@/components/shared'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { useLoadRun } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { cn, shortId } from '@/lib/utils'

function Tile({ label, value, note, ok }: { label: string; value: string; note?: string; ok?: boolean }) {
  return (
    <Card className="p-5">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 text-3xl font-bold tabular-nums">{value}</div>
      {note && <div className={cn('mt-1 text-xs', ok === undefined ? 'text-muted-foreground' : ok ? 'text-green-600 dark:text-green-400' : 'text-amber-600 dark:text-amber-400')}>{note}</div>}
    </Card>
  )
}

export default function LoadTestReportPage() {
  const { id = '' } = useParams()
  useDocumentTitle(`Load test ${shortId(id)}`)
  const { data: l, isLoading, error, refetch } = useLoadRun(id)

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-72" /></div>
  if (error || !l) return <ErrorCard error={error ?? new Error('Load run not found')} onRetry={() => refetch()} />
  if (l.status !== 'completed')
    return (
      <Card className="flex items-center gap-4 border-amber-500/40 bg-amber-500/5 p-6">
        <Loader2 className={cn('size-8 text-amber-500', l.status !== 'failed' && 'animate-spin')} />
        <div><h1 className="text-2xl font-bold">{l.status === 'failed' ? 'Load test failed' : 'Load test running…'}</h1>
          <p className="text-sm text-muted-foreground">{l.concurrency} users for {l.duration_seconds}s. This page updates automatically.</p></div>
      </Card>
    )

  const errPct = (l.error_rate ?? 0) * 100
  const rps = l.throughput_rps ?? 0
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{l.agent_name} — load test</h1>
        <p className="text-sm text-muted-foreground">{l.concurrency} concurrent users · {l.duration_seconds} seconds · {l.total_requests} requests</p>
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="p95 latency" value={`${l.p95_ms}ms`} note={`p50 ${l.p50_ms}ms · p99 ${l.p99_ms}ms`} />
        <Tile label="Error rate" value={`${errPct.toFixed(1)}%`} ok={errPct <= 1} note={errPct <= 1 ? '✓ Within acceptable bounds' : '⚠ Above 1% threshold'} />
        <Tile label="Cost / hour" value={`$${(l.cost_per_hour_usd ?? 0).toFixed(2)}`} ok={(l.cost_per_hour_usd ?? 0) * 10 <= 10} note={(l.cost_per_hour_usd ?? 0) * 10 <= 10 ? '✓ Viable at current scale' : '⚠ High — review before scaling'} />
        <Tile label="Throughput" value={`${rps} req/s`} note={`~${Math.round(rps * 3600).toLocaleString()} req/hour capacity`} />
      </div>
      <Card>
        <CardHeader><CardTitle>p95 latency over time</CardTitle></CardHeader>
        <CardContent>{l.latency_series?.length ? <LatencyChart series={l.latency_series} /> : <p className="text-sm text-muted-foreground">No latency series recorded.</p>}</CardContent>
      </Card>
      <CostViabilityCard load={l} />
    </div>
  )
}
