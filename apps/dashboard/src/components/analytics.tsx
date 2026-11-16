import { AlertTriangle, Bot, CheckCircle2, DatabaseZap, Shuffle, Wrench, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { EmptyState, ErrorCard } from '@/components/shared'
import { Button } from '@/components/ui/button'
import { Badge, Progress, Skeleton, Spinner } from '@/components/ui/misc'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  useCandidates, useClusters, useDismissCluster, useReviewCandidate, useRunMining,
} from '@/hooks/queries'
import type { ARSBreakdown, ARSPoint, DriftAlert, LatencyBucket, LoadRun, TranscriptTurn } from '@/lib/types'
import { ARS_TARGET, arsHex, cn, formatAr, formatCost, formatDateTime, timeAgo } from '@/lib/utils'

const axisProps = { stroke: 'hsl(var(--muted-foreground))', fontSize: 12, tickLine: false, axisLine: false } as const
const tooltipStyle = {
  contentStyle: { background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 },
  labelStyle: { color: 'hsl(var(--muted-foreground))' },
}

// ---------------- ARS trend ----------------
export function ArsTrendChart({ points }: { points: ARSPoint[] }) {
  if (points.length === 0)
    return <EmptyState icon={Bot} title="No ARS history yet" description="Run an eval to start building a reliability trend." />
  const data = points.map((p) => ({ ...p, label: new Date(p.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) }))
  const below = points.filter((p) => p.ars < ARS_TARGET).length
  return (
    <div className="space-y-3">
      <div style={{ height: 400 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 16, right: 24, bottom: 4, left: -8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
            <XAxis dataKey="label" {...axisProps} />
            <YAxis domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.7, 0.9, 1]} {...axisProps} />
            <Tooltip {...tooltipStyle} formatter={(v) => [formatAr(Number(v)), 'ARS']} labelFormatter={(_, p) => `${p?.[0]?.payload?.version_label ?? ''} · ${formatDateTime(p?.[0]?.payload?.created_at)}`} />
            <ReferenceLine y={ARS_TARGET} stroke="hsl(var(--gate-pass))" strokeDasharray="6 2" label={{ value: 'SLO Target 0.9', position: 'insideTopRight', fill: 'hsl(var(--gate-pass))', fontSize: 12 }} />
            <Line type="monotone" dataKey="ars" stroke="hsl(var(--brand))" strokeWidth={2.5} isAnimationActive
              dot={(p: { cx?: number; cy?: number; payload?: ARSPoint; index?: number }) => (
                <circle key={p.index} cx={p.cx} cy={p.cy} r={5} fill={arsHex(p.payload?.ars)} stroke="hsl(var(--background))" strokeWidth={2} />
              )} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className={cn('text-sm', below > 0 ? 'font-medium text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
        ARS has been below target for {below} of the last {points.length} runs
      </p>
    </div>
  )
}

// ---------------- Drift alerts ----------------
export function DriftAlertsList({ alerts }: { alerts: DriftAlert[] }) {
  if (alerts.length === 0)
    return <EmptyState tone="success" icon={CheckCircle2} title="No drift detected" description="Behaviour is stable relative to each agent's rolling baseline." />
  return (
    <div className="space-y-3">
      {alerts.map((a) => {
        const delta = a.current_value - a.baseline_value
        const href = a.diff_run_id ? `/diffs/${a.diff_run_id}` : a.eval_run_id ? `/runs/${a.eval_run_id}` : null
        return (
          <Card key={a.id} className={cn('border-l-4 p-4', a.drift_type === 'model' ? 'border-l-red-500' : 'border-l-amber-500')}>
            <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
              <Shuffle className="size-4" />
              <span className="capitalize">{a.drift_type} drift</span>
              <span className="text-muted-foreground">·</span>
              <span className="font-mono text-xs">{a.metric}</span>
            </div>
            <p className="mt-1.5 text-sm">
              Baseline <span className="font-mono">{a.baseline_value.toFixed(3)}</span> → Current{' '}
              <span className="font-mono">{a.current_value.toFixed(3)}</span>{' '}
              <span className={cn('font-mono', delta < 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600')}>(Δ {delta.toFixed(3)})</span>
            </p>
            <p className="mt-1 text-sm text-muted-foreground">"{a.message}"</p>
            <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
              <span>Detected: {formatDateTime(a.detected_at)}</span>
              {href && <Button asChild variant="link" size="sm"><Link to={href}>Investigate →</Link></Button>}
            </div>
          </Card>
        )
      })}
    </div>
  )
}

// ---------------- ARS breakdown ----------------
const BARS: { key: keyof Omit<ARSBreakdown, 'ars'>; label: string; weight: number }[] = [
  { key: 'correctness', label: 'Correctness', weight: 40 },
  { key: 'safety', label: 'Safety', weight: 20 },
  { key: 'latency', label: 'Latency', weight: 20 },
  { key: 'cost', label: 'Cost', weight: 20 },
]
const barColor = (v: number) => (v >= 0.9 ? 'bg-green-500' : v >= 0.7 ? 'bg-amber-500' : 'bg-red-500')

export function ArsBreakdownBars({ ars }: { ars: ARSBreakdown }) {
  return (
    <Card>
      <CardHeader><CardTitle>ARS Breakdown</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {BARS.map((b) => (
          <div key={b.key} className="grid grid-cols-[88px_1fr_auto] items-center gap-3 text-sm">
            <span>{b.label}</span>
            <Progress value={ars[b.key] * 100} indicatorClassName={barColor(ars[b.key])} />
            <span className="w-32 text-right font-mono text-xs">{ars[b.key].toFixed(3)} <span className="text-muted-foreground">({b.weight}%)</span></span>
          </div>
        ))}
        <div className="flex items-center justify-between border-t pt-3 text-sm font-semibold">
          <span>ARS (composite)</span>
          <span className="font-mono text-base" style={{ color: arsHex(ars.ars) }}>{ars.ars.toFixed(3)}</span>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------- Transcript ----------------
export function TranscriptViewer({ transcript }: { transcript: TranscriptTurn[] }) {
  return (
    <div className="space-y-3 py-1">
      {transcript.map((t, i) => (
        <div key={i} className="space-y-2">
          {t.role === 'assistant' && t.tool_calls?.map((c, j) => (
            <div key={j} className="mx-auto max-w-[90%] rounded-md border border-dashed bg-muted/40 px-3 py-1.5 font-mono text-xs text-muted-foreground">
              <Wrench className="mr-1.5 inline size-3" />{c.name} {JSON.stringify(c.arguments)}
              <span className="ml-2 opacity-70">→ {JSON.stringify(c.result)}</span>
            </div>
          ))}
          <div className={cn('flex', t.role === 'user' ? 'justify-start' : 'justify-end')}>
            <div className={cn('max-w-[85%] rounded-2xl px-4 py-2.5 text-sm', t.role === 'user' ? 'rounded-bl-sm border bg-background' : 'rounded-br-sm bg-muted')}>
              <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t.role}</div>
              {t.content}
              {t.role === 'assistant' && (
                <div className="mt-1.5 font-mono text-[11px] text-muted-foreground">Latency: {t.latency_ms}ms · Cost: {formatCost(t.cost_usd)}</div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------- Similarity bar ----------------
export function SimilarityBar({ value, threshold }: { value: number; threshold: number }) {
  const ok = value >= threshold
  return (
    <div className="flex items-center gap-3">
      <Progress value={value * 100} className="max-w-56" indicatorClassName={ok ? 'bg-green-500' : 'bg-red-500'} />
      <span className={cn('font-mono text-sm', ok ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>{value.toFixed(3)}</span>
    </div>
  )
}

// ---------------- Load test visuals ----------------
export function LatencyChart({ series }: { series: LatencyBucket[] }) {
  const SLO = 200
  return (
    <div style={{ height: 260 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={series} margin={{ top: 12, right: 16, bottom: 4, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis dataKey="t" tickFormatter={(v) => `${v}s`} {...axisProps} />
          <YAxis {...axisProps} unit="ms" />
          <Tooltip {...tooltipStyle} formatter={(v) => [`${v}ms`, 'p95']} labelFormatter={(v) => `t = ${v}s`} />
          <ReferenceLine y={SLO} stroke="hsl(var(--gate-pass))" strokeDasharray="6 2" label={{ value: 'p95 SLO', position: 'insideTopRight', fill: 'hsl(var(--gate-pass))', fontSize: 12 }} />
          <Bar dataKey="p95_ms" radius={[4, 4, 0, 0]}>
            {series.map((b, i) => <Cell key={i} fill={b.p95_ms > SLO ? 'hsl(var(--gate-fail))' : 'hsl(var(--gate-pass))'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function CostViabilityCard({ load }: { load: LoadRun }) {
  const cph = load.cost_per_hour_usd ?? 0
  const viable = cph * 10 <= 10
  return (
    <Card>
      <CardHeader><CardTitle>Cost Analysis</CardTitle></CardHeader>
      <CardContent className="space-y-1.5 font-mono text-sm">
        <div className="flex justify-between"><span>Current load ({load.concurrency} users):</span><span>{formatCost(cph)}/hour</span></div>
        <div className="flex justify-between"><span>Projected at 10× load:</span><span>~{formatCost(cph * 10)}/hour</span></div>
        <div className="flex justify-between"><span>Projected at 100× load:</span><span>~{formatCost(cph * 100)}/hour</span></div>
        <p className={cn('pt-2 font-sans font-medium', viable ? 'text-green-600 dark:text-green-400' : 'text-amber-600 dark:text-amber-400')}>
          {viable ? '● Financially viable at current scale' : `○ Review before exceeding ${load.concurrency} concurrent users`}
        </p>
        <p className="font-sans text-xs text-muted-foreground">Linear projection — an estimate, not a capacity model.</p>
      </CardContent>
    </Card>
  )
}

// ---------------- Failure clusters ----------------
export function FailureClustersPanel({ agentId }: { agentId: string }) {
  const clusters = useClusters(agentId)
  const candidates = useCandidates(agentId)
  const mining = useRunMining(agentId)
  const dismiss = useDismissCluster(agentId)
  const review = useReviewCandidate(agentId)

  if (clusters.isLoading) return <Skeleton className="h-40 w-full" />
  if (clusters.error) return <ErrorCard error={clusters.error} onRetry={() => clusters.refetch()} />

  const runMining = () =>
    mining.mutate(undefined, {
      onSuccess: (r) => toast.success(r.length ? `Found ${r.length} failure cluster${r.length > 1 ? 's' : ''}` : 'No failing cases to cluster'),
      onError: (e) => toast.error(e.message),
    })

  if (!clusters.data?.length)
    return (
      <Card>
        <EmptyState icon={DatabaseZap} title="No failure clusters yet" description="Run the mining analysis to auto-discover recurring failure patterns."
          action={<Button onClick={runMining} disabled={mining.isPending}>{mining.isPending && <Spinner />}Run Mining Analysis</Button>} />
      </Card>
    )

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={runMining} disabled={mining.isPending}>{mining.isPending && <Spinner />}Re-run mining</Button>
      </div>
      {clusters.data.map((c) => (
        <Card key={c.id} className="p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">Cluster {c.cluster_index}</span>
            <span className="text-muted-foreground">· {c.case_count} case{c.case_count > 1 ? 's' : ''} ·</span>
            <Badge variant={c.bad_outcome_rate >= 0.5 ? 'fail' : 'warn'}>{Math.round(c.bad_outcome_rate * 100)}% bad outcome</Badge>
          </div>
          <p className="mt-2 font-medium">"{c.label}"</p>
          <p className="mt-1 text-sm text-muted-foreground">Representative: "{c.representative}"</p>
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={() => toast.success('Case promoted — add it to your eval suite YAML')}>Promote to Test Suite</Button>
            <Button size="sm" variant="outline" onClick={() => dismiss.mutate(c.id, { onSuccess: () => toast.success('Cluster dismissed') })}>Dismiss</Button>
          </div>
        </Card>
      ))}

      {!!candidates.data?.length && (
        <Card>
          <CardHeader><CardTitle>Pending review</CardTitle></CardHeader>
          <CardContent className="divide-y">
            {candidates.data.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-xs">{c.case_key}</span>
                  <span className="text-xs text-muted-foreground">Created {timeAgo(c.created_at)}</span>
                </span>
                <Button size="sm" variant="outline" onClick={() => review.mutate({ id: c.id, decision: 'approve' }, { onSuccess: () => toast.success('Candidate approved') })}>Approve</Button>
                <Button size="sm" variant="ghost" onClick={() => review.mutate({ id: c.id, decision: 'reject' }, { onSuccess: () => toast.success('Candidate rejected') })}>Reject</Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export const ReasonList = ({ reasons }: { reasons: string[] }) => (
  <ul className="space-y-1.5">
    {reasons.map((r) => (
      <li key={r} className="flex items-start gap-2 text-sm"><XCircle className="mt-0.5 size-4 shrink-0 text-red-500" />{r}</li>
    ))}
  </ul>
)

export const WarnIcon = AlertTriangle
