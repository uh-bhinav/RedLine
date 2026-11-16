import { Bot, Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { RegisterAgentDialog } from '@/components/dialogs'
import { CodeBlock, EmptyState, ErrorCard, GateBadge } from '@/components/shared'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge, Input, Skeleton } from '@/components/ui/misc'
import { useAgents } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import type { AgentListItem } from '@/lib/types'
import { arsColor, cn, formatAr, timeAgo } from '@/lib/utils'

export function AgentsEmptyState() {
  return (
    <EmptyState icon={Bot} title="No agents registered yet" description="Register your first agent using the CLI:"
      action={
        <div className="w-full max-w-md space-y-3 text-left">
          <CodeBlock code="agentbench init --agent my-agent --entrypoint agents.my_agent.agent:run_turn" />
          <Button asChild variant="link" size="sm"><a href="https://github.com/uh-bhinav/RedLine#readme" target="_blank" rel="noreferrer">Read the quickstart →</a></Button>
        </div>
      } />
  )
}

export function AgentsTable({ agents }: { agents: AgentListItem[] }) {
  const navigate = useNavigate()
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
            {['Name', 'ARS', 'Gate Status', 'Last Version', 'Last Run', 'Registered'].map((h) => <th key={h} className="px-4 py-3 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => (
            <tr key={a.id} tabIndex={0} onClick={() => navigate(`/agent/${a.id}`)} onKeyDown={(e) => e.key === 'Enter' && navigate(`/agent/${a.id}`)}
              className="cursor-pointer border-b last:border-0 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none">
              <td className="px-4 py-3">
                <Link to={`/agent/${a.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>{a.name}</Link>
                {a.description && <div className="max-w-xs truncate text-xs text-muted-foreground">{a.description}</div>}
              </td>
              <td className={cn('px-4 py-3 font-mono font-semibold tabular-nums', arsColor(a.latest_ars))}>{formatAr(a.latest_ars)}</td>
              <td className="px-4 py-3"><GateBadge passed={a.latest_run?.gate_passed} status={a.latest_run?.status} /></td>
              <td className="px-4 py-3">{a.latest_version_label ? <Badge variant="outline">{a.latest_version_label}</Badge> : '—'}</td>
              <td className="px-4 py-3 text-muted-foreground">{timeAgo(a.latest_run?.created_at)}</td>
              <td className="px-4 py-3 text-muted-foreground">{timeAgo(a.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const FILTERS = ['All', 'PASS', 'FAIL', 'No Runs'] as const

export default function AgentsListPage() {
  useDocumentTitle('Agents')
  const { data, isLoading, error, refetch } = useAgents()
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('All')
  const [query, setQuery] = useState('')

  const shown = useMemo(() => (data ?? []).filter((a) => {
    const g = a.latest_run?.gate_passed
    const okFilter = filter === 'All' || (filter === 'PASS' && g === true) || (filter === 'FAIL' && g === false) || (filter === 'No Runs' && !a.latest_run)
    return okFilter && a.name.toLowerCase().includes(query.toLowerCase())
  }), [data, filter, query])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Agents</h1><p className="text-sm text-muted-foreground">Every registered agent and its latest reliability verdict.</p></div>
        <RegisterAgentDialog><Button variant="brand"><Plus />Register Agent</Button></RegisterAgentDialog>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search agents…" className="pl-9" aria-label="Search agents" />
        </div>
        <div className="flex gap-1 rounded-lg bg-muted p-1" role="group" aria-label="Filter by gate status">
          {FILTERS.map((f) => (
            <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f}
              className={cn('rounded-md px-3 py-1 text-sm font-medium transition-colors', filter === f ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground')}>{f}</button>
          ))}
        </div>
      </div>

      <Card>
        {isLoading ? <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
          : error ? <div className="p-5"><ErrorCard error={error} onRetry={() => refetch()} /></div>
          : !data?.length ? <AgentsEmptyState />
          : shown.length === 0 ? <EmptyState icon={Search} title="No agents match" description="Try a different filter or search term." />
          : <AgentsTable agents={shown} />}
      </Card>
    </div>
  )
}
