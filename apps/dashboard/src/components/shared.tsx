import { motion } from 'framer-motion'
import { AlertTriangle, Check, CheckCircle2, Copy, Loader2, RefreshCw, X, XCircle, type LucideIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import CountUpModule from 'react-countup'
import { PolarAngleAxis, RadialBar, RadialBarChart } from 'recharts'
import { Alert, Badge } from '@/components/ui/misc'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ApiError } from '@/lib/api'
import type { BudgetStatus, ErrorBudget } from '@/lib/types'
import { arsHex, cn } from '@/lib/utils'

// react-countup is CJS; depending on the bundler its default import arrives wrapped.
const CountUp = ((CountUpModule as unknown as { default?: typeof CountUpModule }).default ?? CountUpModule) as typeof CountUpModule

// ---------------- Logo ----------------
export function Logo({ className, size = 28 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="8" fill="hsl(var(--brand))" />
      <path d="M8 22V10h7a4 4 0 0 1 0 8h-7m6 0 5 4" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ---------------- Gate badge ----------------
export function GateBadge({ passed, status }: { passed: boolean | null | undefined; status?: string }) {
  if (status === 'pending' || status === 'running')
    return <Badge variant="warn"><Loader2 className="size-3 animate-spin" />{status === 'running' ? 'RUNNING' : 'QUEUED'}</Badge>
  if (status === 'failed') return <Badge variant="fail"><XCircle className="size-3" />ERROR</Badge>
  if (passed == null) return <Badge variant="secondary">NO RUNS</Badge>
  return passed
    ? <Badge variant="pass"><CheckCircle2 className="size-3" />PASS</Badge>
    : <Badge variant="fail"><XCircle className="size-3" />FAIL</Badge>
}

// ---------------- Empty / error states ----------------
export function EmptyState({ icon: Icon, title, description, action, tone = 'default' }: {
  icon: LucideIcon; title: string; description?: ReactNode; action?: ReactNode; tone?: 'default' | 'success'
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className={cn('mb-1 flex size-14 items-center justify-center rounded-2xl', tone === 'success' ? 'bg-green-500/10 text-green-600 dark:text-green-400' : 'bg-muted text-muted-foreground')}>
        <Icon className="size-7" />
      </div>
      <h3 className="text-lg font-semibold">{title}</h3>
      {description && <div className="max-w-md text-sm text-muted-foreground">{description}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

export function ErrorCard({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError || error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <Alert variant="destructive" className="items-center">
      <AlertTriangle />
      <div className="flex-1">{message}</div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}><RefreshCw />Retry</Button>
      )}
    </Alert>
  )
}

// ---------------- Summary card ----------------
export function SummaryCard({ icon: Icon, label, value, decimals = 0, suffix, text, tone = 'default', sub, index = 0 }: {
  icon: LucideIcon; label: string; value?: number; decimals?: number; suffix?: string; text?: string
  tone?: 'default' | 'good' | 'warn' | 'bad'; sub?: string; index?: number
}) {
  const toneClass = { default: '', good: 'text-green-600 dark:text-green-400', warn: 'text-amber-600 dark:text-amber-400', bad: 'text-red-600 dark:text-red-400' }[tone]
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05, duration: 0.3 }}>
      <Card className="p-5">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{label}</span>
          <Icon className="size-4" />
        </div>
        <div className={cn('mt-2 text-3xl font-bold tabular-nums', toneClass)}>
          {text ?? <CountUp end={value ?? 0} decimals={decimals} duration={0.8} suffix={suffix} preserveValue />}
        </div>
        {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
      </Card>
    </motion.div>
  )
}

// ---------------- Alert strip ----------------
export interface StripAlert { id: string; message: string; href: string; tone: 'warn' | 'bad' }
const DISMISS_KEY = 'rl_dismissed_alerts'
const readDismissed = (): string[] => {
  try { return JSON.parse(sessionStorage.getItem(DISMISS_KEY) ?? '[]') } catch { return [] }
}

export function AlertStrip({ alerts, onView }: { alerts: StripAlert[]; onView: (href: string) => void }) {
  const [dismissed, setDismissed] = useState<string[]>(readDismissed)
  const visible = alerts.filter((a) => !dismissed.includes(a.id)).slice(0, 3)
  const dismiss = (id: string) => {
    const next = [...dismissed, id]
    setDismissed(next)
    try { sessionStorage.setItem(DISMISS_KEY, JSON.stringify(next)) } catch { /* storage unavailable */ }
  }

  if (visible.length === 0)
    return (
      <Alert variant="success" className="items-center"><CheckCircle2 /><span className="font-medium">No active alerts — every agent is within its reliability targets.</span></Alert>
    )
  return (
    <div className="space-y-2">
      {visible.map((a) => (
        <motion.div key={a.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}
          className={cn('flex items-center gap-3 rounded-lg border border-l-4 bg-card p-3 text-sm', a.tone === 'bad' ? 'border-l-red-500' : 'border-l-amber-500')}>
          <AlertTriangle className={cn('size-4 shrink-0', a.tone === 'bad' ? 'text-red-500' : 'text-amber-500')} />
          <span className="flex-1">{a.message}</span>
          <Button variant="link" size="sm" onClick={() => onView(a.href)}>View →</Button>
          <button aria-label="Dismiss alert" className="text-muted-foreground hover:text-foreground" onClick={() => dismiss(a.id)}><X className="size-4" /></button>
        </motion.div>
      ))}
    </div>
  )
}

// ---------------- ARS ring ----------------
export function ARSRing({ ars, size = 96 }: { ars: number | null | undefined; size?: number }) {
  const color = arsHex(ars)
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <RadialBarChart width={size} height={size} innerRadius="76%" outerRadius="100%" data={[{ v: (ars ?? 0) * 100 }]} startAngle={225} endAngle={-45}>
        <PolarAngleAxis type="number" domain={[0, 100]} tick={false} angleAxisId={0} />
        <RadialBar dataKey="v" angleAxisId={0} cornerRadius={8} fill={color} background={{ fill: 'hsl(var(--muted))' }} isAnimationActive animationDuration={900} />
      </RadialBarChart>
      <div className="absolute inset-0 flex items-center justify-center text-xl font-bold tabular-nums" style={{ color }}>
        {ars == null ? '—' : <CountUp end={ars} decimals={2} duration={0.9} />}
      </div>
    </div>
  )
}

// ---------------- Error budget pill ----------------
const BUDGET_STYLE: Record<BudgetStatus, { label: string; variant: 'pass' | 'warn' | 'fail' }> = {
  healthy: { label: 'HEALTHY', variant: 'pass' },
  at_risk: { label: 'AT RISK', variant: 'warn' },
  frozen: { label: 'FROZEN', variant: 'fail' },
}

export function budgetSentence(b: ErrorBudget): string {
  if (b.status === 'frozen') return `DEPLOYMENTS FROZEN — ${b.breached}/${b.runs_considered} runs below target`
  if (b.status === 'at_risk') return `${b.above_target}/${b.runs_considered} runs above target (${b.breached} breached)`
  return `${b.above_target}/${b.runs_considered} runs above target`
}

export function ErrorBudgetGauge({ budget }: { budget: ErrorBudget }) {
  const s = BUDGET_STYLE[budget.status]
  return (
    <div className="space-y-2">
      <Badge variant={s.variant} className="px-3 py-1 text-sm">{s.label}</Badge>
      <p className="text-sm text-muted-foreground">{budgetSentence(budget)}</p>
      <div className="flex gap-1" aria-hidden>
        {Array.from({ length: budget.window }).map((_, i) => (
          <span key={i} className={cn('h-1.5 flex-1 rounded-full', i < budget.breached ? 'bg-red-500' : i < budget.runs_considered ? 'bg-green-500' : 'bg-muted')} />
        ))}
      </div>
    </div>
  )
}

// ---------------- Copyable code block ----------------
export function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch { /* clipboard unavailable */ }
  }
  return (
    <div className="group relative">
      {label && <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>}
      <pre className="overflow-x-auto rounded-lg border bg-muted/60 p-3 pr-12 font-mono text-[13px] leading-relaxed">{code}</pre>
      <Button size="icon" variant="ghost" className={cn('absolute right-1.5 size-8', label ? 'top-6' : 'top-1.5')} onClick={copy} aria-label="Copy to clipboard">
        {copied ? <Check className="text-green-500" /> : <Copy />}
      </Button>
    </div>
  )
}

// ---------------- Password strength ----------------
export function PasswordStrengthBar({ password }: { password: string }) {
  const checks = [password.length >= 8, /[A-Z]/.test(password), /[a-z]/.test(password), /[\d\W]/.test(password)]
  const score = password ? checks.filter(Boolean).length : 0
  const palette = ['bg-muted', 'bg-red-500', 'bg-orange-500', 'bg-yellow-500', 'bg-green-500']
  const label = ['', 'Weak', 'Fair', 'Good', 'Strong'][score]
  return (
    <div className="space-y-1" aria-live="polite">
      <div className="flex gap-1.5">
        {[1, 2, 3, 4].map((i) => (
          <span key={i} className={cn('h-1.5 flex-1 rounded-full transition-colors', i <= score ? palette[score] : 'bg-muted')} />
        ))}
      </div>
      <p className="h-4 text-xs text-muted-foreground">{label}</p>
    </div>
  )
}
