import { Activity, ArrowLeft } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EmptyState, ErrorCard } from '@/components/shared'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { useTraces } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import type { TraceEvent } from '@/lib/types'
import { cn, formatCost, shortId } from '@/lib/utils'

const KIND_STYLE = { user: 'bg-slate-400', tool: 'bg-violet-500', assistant: 'bg-brand' } as const

export default function TraceViewerPage() {
  const { id = '' } = useParams()
  useDocumentTitle(`Traces — Run ${shortId(id)}`)
  const { data, isLoading, error, refetch } = useTraces(id)

  const groups = useMemo(() => {
    const map = new Map<string, TraceEvent[]>()
    for (const e of data ?? []) map.set(e.case_key, [...(map.get(e.case_key) ?? []), e])
    return [...map.entries()]
  }, [data])
  const maxLatency = Math.max(1, ...(data ?? []).map((e) => e.latency_ms ?? 0))

  if (isLoading) return <Skeleton className="h-96" />
  if (error) return <ErrorCard error={error} onRetry={() => refetch()} />

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Trace timeline</h1>
        <Button asChild variant="outline" size="sm"><Link to={`/runs/${id}`}><ArrowLeft />Back to run</Link></Button>
      </div>
      {groups.length === 0 ? <Card><EmptyState icon={Activity} title="No trace events recorded" description="Traces appear once a run has completed." /></Card> : groups.map(([caseKey, events]) => {
        const totalLatency = events.reduce((s, e) => s + (e.latency_ms ?? 0), 0)
        const totalCost = events.reduce((s, e) => s + (e.cost_usd ?? 0), 0)
        return (
          <Card key={caseKey} className="p-5">
            <h2 className="mb-3 font-mono text-sm font-semibold">{caseKey}</h2>
            <ol className="space-y-2">
              {events.map((e, i) => {
                const failed = e.kind === 'assistant' && e.passed === false
                return (
                  <li key={i} className="grid grid-cols-[88px_1fr] items-center gap-3 text-sm sm:grid-cols-[88px_minmax(0,2fr)_minmax(0,3fr)]">
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">T{e.turn} · {e.name ?? e.kind}</span>
                    <span className="truncate" title={e.content}>{e.content}</span>
                    <div className="col-span-2 flex items-center gap-2 sm:col-span-1">
                      <div className="h-3 flex-1 rounded-full bg-muted">
                        {e.latency_ms != null && (
                          <div className={cn('h-3 rounded-full', failed ? 'bg-destructive' : KIND_STYLE[e.kind])} style={{ width: `${Math.max(3, (e.latency_ms / maxLatency) * 100)}%` }} />
                        )}
                      </div>
                      <span className="w-20 text-right font-mono text-xs text-muted-foreground">{e.latency_ms != null ? `${e.latency_ms}ms` : ''}</span>
                      {failed && <span className="text-xs font-semibold text-destructive">← FAILED</span>}
                    </div>
                  </li>
                )
              })}
            </ol>
            <div className="mt-4 flex gap-6 border-t pt-3 font-mono text-xs text-muted-foreground">
              <span>Total latency: <b className="text-foreground">{totalLatency}ms</b></span>
              <span>Total cost: <b className="text-foreground">{formatCost(totalCost)}</b></span>
            </div>
          </Card>
        )
      })}
    </div>
  )
}
