import { useState, type FormEvent, type ReactNode, type SelectHTMLAttributes } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Alert, Input, Label, Spinner } from '@/components/ui/misc'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/overlay'
import { useCreateDiff, useCreateEvalRun, useCreateLoadRun, useRegisterAgent } from '@/hooks/queries'
import type { AgentDetail } from '@/lib/types'
import { cn } from '@/lib/utils'

function Select({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn('flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', className)}
      {...p}
    />
  )
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

// ---------------- Register agent ----------------
export function RegisterAgentDialog({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [entrypoint, setEntrypoint] = useState('')
  const register = useRegisterAgent()
  const navigate = useNavigate()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    register.mutate({ name: name.trim(), description: description.trim(), entrypoint: entrypoint.trim() }, {
      onSuccess: (agent) => {
        toast.success(`Agent "${name.trim()}" registered`)
        setOpen(false)
        navigate(`/agent/${agent.id}`)
      },
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Register Agent</DialogTitle>
            <DialogDescription>Add an agent so RedLine can evaluate it.</DialogDescription>
          </DialogHeader>
          <Field label="Name"><Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="my-agent" /></Field>
          <Field label="Description (optional)"><Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Customer support RAG agent" /></Field>
          <Field label="Entrypoint" hint="Python: agents.rag_agent.agent:run_turn  |  HTTP: http://host/turn">
            <Input required value={entrypoint} onChange={(e) => setEntrypoint(e.target.value)} placeholder="agents.my_agent.agent:run_turn" className="font-mono" />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={register.isPending}>{register.isPending && <Spinner />}Register</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------- shared version/suite pickers ----------------
function useSelection(agent: AgentDetail) {
  const [versionId, setVersionId] = useState(agent.latest_version?.id ?? '')
  const [suiteId, setSuiteId] = useState(agent.suites[0]?.id ?? '')
  return { versionId, setVersionId, suiteId, setSuiteId }
}

function VersionSelect({ agent, value, onChange, label = 'Agent version' }: { agent: AgentDetail; value: string; onChange: (v: string) => void; label?: string }) {
  return (
    <Field label={label}>
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        {agent.versions.map((v) => <option key={v.id} value={v.id}>{v.version_label} · {v.model_name}</option>)}
      </Select>
    </Field>
  )
}

function SuiteSelect({ agent, value, onChange }: { agent: AgentDetail; value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Eval suite">
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        {agent.suites.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.case_count} cases)</option>)}
      </Select>
    </Field>
  )
}

function NoSuites() {
  return <Alert variant="warning">This agent has no eval suite yet. Push one with <code className="font-mono">agentbench push-suite</code>.</Alert>
}

// ---------------- Trigger eval ----------------
export function TriggerEvalRunDialog({ agent, children }: { agent: AgentDetail; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const sel = useSelection(agent)
  const create = useCreateEvalRun()
  const navigate = useNavigate()
  const ready = agent.suites.length > 0 && agent.versions.length > 0

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Trigger Eval Run</DialogTitle>
          <DialogDescription>Runs the suite against the selected version and evaluates the gate.</DialogDescription>
        </DialogHeader>
        {ready ? (
          <>
            <VersionSelect agent={agent} value={sel.versionId} onChange={sel.setVersionId} />
            <SuiteSelect agent={agent} value={sel.suiteId} onChange={sel.setSuiteId} />
          </>
        ) : <NoSuites />}
        <DialogFooter>
          <Button disabled={!ready || create.isPending} onClick={() =>
            create.mutate({ agent_version_id: sel.versionId, suite_id: sel.suiteId }, {
              onSuccess: (run) => { toast.success('Eval run started — navigating to run detail'); setOpen(false); navigate(`/runs/${run.id}`) },
              onError: (e) => toast.error(e.message),
            })}>
            {create.isPending && <Spinner />}Run Eval
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------- Trigger diff ----------------
export function TriggerDiffRunDialog({ agent, children }: { agent: AgentDetail; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [suiteId, setSuiteId] = useState(agent.suites[0]?.id ?? '')
  const [a, setA] = useState(agent.versions[1]?.id ?? agent.latest_version?.id ?? '')
  const [b, setB] = useState(agent.latest_version?.id ?? '')
  const create = useCreateDiff()
  const navigate = useNavigate()
  const ready = agent.suites.length > 0 && agent.versions.length > 0

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Behavioural Diff</DialogTitle>
          <DialogDescription>Compare what two versions say on the same suite. Pick the same version twice to detect silent model drift.</DialogDescription>
        </DialogHeader>
        {ready ? (
          <>
            <VersionSelect agent={agent} label="Version A (baseline)" value={a} onChange={setA} />
            <VersionSelect agent={agent} label="Version B (candidate)" value={b} onChange={setB} />
            <SuiteSelect agent={agent} value={suiteId} onChange={setSuiteId} />
          </>
        ) : <NoSuites />}
        <DialogFooter>
          <Button disabled={!ready || create.isPending} onClick={() =>
            create.mutate({ agent_id: agent.id, suite_id: suiteId, version_a_id: a, version_b_id: b }, {
              onSuccess: (d) => { toast.success('Diff run created'); setOpen(false); navigate(`/diffs/${d.id}`) },
              onError: (e) => toast.error(e.message),
            })}>
            {create.isPending && <Spinner />}Run Diff
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------- Trigger load test ----------------
export function TriggerLoadRunDialog({ agent, children }: { agent: AgentDetail; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const sel = useSelection(agent)
  const [concurrency, setConcurrency] = useState(10)
  const [duration, setDuration] = useState(20)
  const create = useCreateLoadRun()
  const navigate = useNavigate()
  const ready = agent.suites.length > 0 && agent.versions.length > 0

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Run Load Test</DialogTitle>
          <DialogDescription>Simulates concurrent users replaying the suite to measure p95 latency, errors and cost.</DialogDescription>
        </DialogHeader>
        {ready ? (
          <>
            <VersionSelect agent={agent} value={sel.versionId} onChange={sel.setVersionId} />
            <SuiteSelect agent={agent} value={sel.suiteId} onChange={sel.setSuiteId} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Concurrent users"><Input type="number" min={1} max={50} value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))} /></Field>
              <Field label="Duration (seconds)"><Input type="number" min={5} max={120} value={duration} onChange={(e) => setDuration(Number(e.target.value))} /></Field>
            </div>
          </>
        ) : <NoSuites />}
        <DialogFooter>
          <Button disabled={!ready || create.isPending} onClick={() =>
            create.mutate({ agent_version_id: sel.versionId, suite_id: sel.suiteId, concurrency, duration_seconds: duration }, {
              onSuccess: (l) => { toast.success('Load test started'); setOpen(false); navigate(`/load-run/${l.id}`) },
              onError: (e) => toast.error(e.message),
            })}>
            {create.isPending && <Spinner />}Start Load Test
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
