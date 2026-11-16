import { AlertOctagon, CheckCircle2, GitCompare, Loader2, MinusCircle, ShieldCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { SimilarityBar } from '@/components/analytics'
import { EmptyState, ErrorCard, GateBadge } from '@/components/shared'
import { Card } from '@/components/ui/card'
import { Badge, Skeleton } from '@/components/ui/misc'
import { useDiff } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import type { DiffClass } from '@/lib/types'
import { cn, shortId } from '@/lib/utils'

export const CLASSIFICATION: Record<DiffClass, { title: string; description: string; box: string; icon: React.ReactNode }> = {
  silent_drift: {
    title: 'SILENT DRIFT DETECTED',
    description: 'The code content hash is identical between both versions. Behavior changed anyway — the model provider likely updated the underlying model without notice. This would be invisible to a code review.',
    box: 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/60',
    icon: <AlertOctagon className="size-7 text-red-600" />,
  },
  safe_refactor: {
    title: 'SAFE REFACTOR',
    description: 'Code changed, but agent behavior stayed the same. Safe to ship.',
    box: 'border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950/60',
    icon: <ShieldCheck className="size-7 text-blue-600" />,
  },
  expected_change: {
    title: 'EXPECTED CHANGE',
    description: 'Code changed and behavior changed as intended.',
    box: 'border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/60',
    icon: <CheckCircle2 className="size-7 text-green-600" />,
  },
  no_op: {
    title: 'NO CHANGE',
    description: 'Neither code nor behavior changed between these versions.',
    box: 'border-border bg-muted/50',
    icon: <MinusCircle className="size-7 text-muted-foreground" />,
  },
}

export default function DiffViewerPage() {
  const { id = '' } = useParams()
  useDocumentTitle(`Diff ${shortId(id)}`)
  const { data: diff, isLoading, error, refetch } = useDiff(id)

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-36" /><Skeleton className="h-64" /></div>
  if (error || !diff) return <ErrorCard error={error ?? new Error('Diff not found')} onRetry={() => refetch()} />

  if (diff.status !== 'completed')
    return (
      <Card className="flex items-center gap-4 border-amber-500/40 bg-amber-500/5 p-6">
        {diff.status === 'failed' ? <AlertOctagon className="size-8 text-red-500" /> : <Loader2 className="size-8 animate-spin text-amber-500" />}
        <div><h1 className="text-2xl font-bold">{diff.status === 'failed' ? 'Diff failed' : 'Comparing versions…'}</h1>
          <p className="text-sm text-muted-foreground">{diff.status === 'failed' ? 'The worker could not finish this diff. Check the worker logs.' : 'The worker is running both versions. This page updates automatically.'}</p></div>
      </Card>
    )

  const hero = CLASSIFICATION[diff.classification ?? 'no_op']
  return (
    <div className="space-y-6">
      <Card className={cn('flex items-start gap-4 border-2 p-6', hero.box)}>
        <div className="mt-1">{hero.icon}</div>
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">{hero.title}</h1>
          <p className="max-w-3xl text-sm">{hero.description}</p>
          <p className="pt-1 font-mono text-sm text-muted-foreground">Mean similarity: {diff.mean_similarity?.toFixed(2)} (threshold: {diff.threshold.toFixed(2)})</p>
          <p className="text-sm text-muted-foreground">
            <Link to={`/agent/${diff.agent_id}`} className="hover:underline">{diff.agent_name}</Link> · {diff.version_a_label} → {diff.version_b_label} · code {diff.code_changed ? 'changed' : 'unchanged'}
          </p>
        </div>
      </Card>

      {diff.cases.length === 0 ? <Card><EmptyState icon={GitCompare} title="No shared cases between these runs" /></Card> : (
        <div className="space-y-4">
          {diff.cases.map((c) => {
            const bad = c.similarity < diff.threshold
            return (
              <Card key={c.case_key} className={cn('border-l-4 p-5', bad ? 'border-l-red-500' : 'border-l-transparent')}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h2 className="font-mono text-sm font-semibold">{c.case_key}</h2>
                    {c.description && <p className="text-xs text-muted-foreground">{c.description}</p>}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    A <GateBadge passed={c.passed_a} /> B <GateBadge passed={c.passed_b} />
                  </div>
                </div>
                <div className="mt-3"><SimilarityBar value={c.similarity} threshold={diff.threshold} /></div>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {[['A', diff.version_a_label, c.output_a], ['B', diff.version_b_label, c.output_b]].map(([side, label, text]) => (
                    <div key={side} className="rounded-lg border bg-muted/30 p-3 text-sm">
                      <Badge variant="outline" className="mb-2">Version {side} · {label}</Badge>
                      <p className="whitespace-pre-wrap">{text}</p>
                    </div>
                  ))}
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
