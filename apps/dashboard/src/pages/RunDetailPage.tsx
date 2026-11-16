import { motion } from 'framer-motion'
import { Check, CheckCircle2, ChevronDown, ExternalLink, Loader2, XCircle, Zap } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArsBreakdownBars, ReasonList, TranscriptViewer } from '@/components/analytics'
import { ErrorCard } from '@/components/shared'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge, Skeleton } from '@/components/ui/misc'
import { useRun } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import type { CaseResult } from '@/lib/types'
import { cn, formatCost, formatDateTime, shortId, timeAgo } from '@/lib/utils'

function CaseRow({ c }: { c: CaseResult }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={cn('border-l-4 transition-colors', c.passed ? 'border-l-green-500' : 'border-l-red-500')}>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/40">
        {c.passed ? <CheckCircle2 className="size-5 shrink-0 text-green-500" /> : <XCircle className="size-5 shrink-0 text-red-500" />}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-sm font-medium">{c.case_key}</span>
          {c.description && <span className="block truncate text-xs text-muted-foreground">{c.description}</span>}
        </span>
        {c.is_chaos && <Badge variant="warn"><Zap className="size-3" />Chaos-injected</Badge>}
        <span className="hidden font-mono text-xs text-muted-foreground sm:block">{c.metrics.latency_ms}ms · {formatCost(c.metrics.cost_usd)}</span>
        <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="space-y-4 overflow-hidden bg-muted/20 px-4 pb-4 pt-1">
          <div className="space-y-1.5">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Scorers</div>
            {Object.entries(c.scorer_results).map(([name, r]) => (
              <div key={name} className="flex items-start gap-2 text-sm">
                {r.passed ? <Check className="mt-0.5 size-4 shrink-0 text-green-500" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-red-500" />}
                <span className="font-medium">{name.replace('Scorer', '')}</span>
                <span className="text-muted-foreground">— {r.detail}</span>
              </div>
            ))}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Transcript</div>
            <TranscriptViewer transcript={c.transcript} />
          </div>
        </motion.div>
      )}
    </div>
  )
}

export default function RunDetailPage() {
  const { id = '' } = useParams()
  const { data: run, isLoading, error, refetch } = useRun(id)
  useDocumentTitle(run?.gate_result ? (run.gate_result.passed ? 'Gate passed' : 'Gate failed') : `Run ${shortId(id)}`)

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-48" /><Skeleton className="h-64" /></div>
  if (error || !run) return <ErrorCard error={error ?? new Error('Run not found')} onRetry={() => refetch()} />

  const active = run.status === 'pending' || run.status === 'running'
  const gate = run.gate_result

  return (
    <div className="space-y-6">
      {active ? (
        <Card className="flex items-center gap-4 border-amber-500/40 bg-amber-500/5 p-6">
          <Loader2 className="size-8 animate-spin text-amber-500" />
          <div>
            <h1 className="text-2xl font-bold">{run.status === 'running' ? 'Evaluating…' : 'Queued'}</h1>
            <p className="text-sm text-muted-foreground">Waiting for the worker. This page updates automatically.</p>
          </div>
        </Card>
      ) : run.status === 'failed' ? (
        <Card className="border-red-500/40 bg-red-500/5 p-6">
          <h1 className="flex items-center gap-3 text-3xl font-bold text-red-600"><XCircle className="size-9" />RUN ERRORED</h1>
          <p className="mt-2 text-sm text-muted-foreground">The worker failed before finishing. Common cause: the agent's LLM key is missing. Check the worker logs.</p>
        </Card>
      ) : gate && (
        <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}>
          <Card className={cn('border-2 p-6', gate.passed ? 'border-green-500/50 bg-green-500/5' : 'border-red-500/50 bg-red-500/5')}>
            <h1 className={cn('flex items-center gap-3 text-3xl font-bold', gate.passed ? 'text-green-600' : 'text-red-600')}>
              {gate.passed ? <CheckCircle2 className="size-10" /> : <XCircle className="size-10" />}
              {gate.passed ? 'GATE PASSED' : 'GATE FAILED'}
            </h1>
            {gate.reasons.length > 0 ? <div className="mt-4"><ReasonList reasons={gate.reasons} /></div>
              : <p className="mt-3 text-sm text-muted-foreground">Every threshold was met — safe to ship.</p>}
            <div className="mt-4 flex flex-wrap gap-x-3 gap-y-1 border-t pt-3 text-sm text-muted-foreground">
              <span className="font-mono">Run {shortId(run.id)}</span>·
              <Link to={`/agent/${run.agent_id}`} className="hover:text-foreground hover:underline">{run.agent_name} {run.version_label}</Link>·
              <span>{run.suite_name} suite</span>·
              <span className="capitalize">Triggered by: {run.triggered_by}</span>·
              <span title={formatDateTime(run.completed_at)}>Completed {timeAgo(run.completed_at)}</span>
            </div>
          </Card>
        </motion.div>
      )}

      {run.ars && <ArsBreakdownBars ars={run.ars} />}

      <Card>
        <div className="flex items-center justify-between p-4">
          <h2 className="font-semibold">Case results {run.cases.length > 0 && <span className="text-muted-foreground">({run.cases.filter((c) => c.passed).length}/{run.cases.length} passed)</span>}</h2>
          <Button asChild variant="outline" size="sm"><Link to={`/runs/${run.id}/traces`}><ExternalLink />View Traces</Link></Button>
        </div>
        <div className="divide-y border-t">
          {run.cases.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">{active ? 'Results will appear here as cases finish.' : 'No case results recorded.'}</p>
            : run.cases.map((c) => <CaseRow key={c.id} c={c} />)}
        </div>
      </Card>
    </div>
  )
}
