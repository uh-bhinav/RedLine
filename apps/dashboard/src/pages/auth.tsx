import { motion } from 'framer-motion'
import { Activity, AlertTriangle, ArrowRight, Check, Eye, EyeOff, GitCompare, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { CodeBlock, Logo, PasswordStrengthBar } from '@/components/shared'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Alert, Input, Label, Spinner } from '@/components/ui/misc'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/overlay'
import { useCreateApiKey } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/utils'

function AuthLayout({ title, children }: { title: string; children: ReactNode }) {
  const features = [
    { icon: ShieldCheck, text: 'Deploy-time gates — block bad agents before production' },
    { icon: GitCompare, text: 'Behavioral diff — catch silent model drift' },
    { icon: Activity, text: 'Error budgets — SRE-grade reliability for AI agents' },
  ]
  return (
    <div className="grid min-h-screen lg:grid-cols-[2fr_3fr]">
      <div className="relative hidden flex-col items-center justify-center gap-8 bg-gradient-to-br from-slate-900 to-slate-800 p-12 text-white lg:flex">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(59,130,246,0.25),transparent_55%)]" />
        <div className="relative flex flex-col items-center gap-3 text-center">
          <Logo size={72} />
          <h1 className="text-4xl font-bold">RedLine</h1>
          <p className="text-slate-300">Agent Reliability Engineering</p>
        </div>
        <ul className="relative space-y-4">
          {features.map((f) => (
            <li key={f.text} className="flex items-center gap-3 text-sm text-slate-200">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/10"><f.icon className="size-4" /></span>
              {f.text}
            </li>
          ))}
        </ul>
      </div>
      <div className="flex items-center justify-center p-6 sm:p-12">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-sm space-y-6">
          <div className="flex items-center gap-2 lg:hidden"><Logo /><span className="text-xl font-bold">RedLine</span></div>
          <h2 className="text-2xl font-semibold">{title}</h2>
          {children}
        </motion.div>
      </div>
    </div>
  )
}

function PasswordInput({ value, onChange, id, autoComplete, disabled }: {
  value: string; onChange: (v: string) => void; id: string; autoComplete: string; disabled?: boolean
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <Input id={id} type={show ? 'text' : 'password'} value={value} onChange={(e) => onChange(e.target.value)}
        required autoComplete={autoComplete} disabled={disabled} className="pr-10" />
      <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide password' : 'Show password'}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}

export function LoginPage() {
  useDocumentTitle('Sign in')
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout title="Sign in to RedLine">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert variant="destructive"><AlertTriangle /><span>{error}</span></Alert>}
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" disabled={busy} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="current-password" disabled={busy} />
        </div>
        <Button type="submit" className="w-full" disabled={busy}>{busy ? <Spinner /> : null}Sign in</Button>
        <button type="button" className="w-full text-center text-xs text-muted-foreground hover:text-foreground"
          onClick={() => { setEmail('demo@redline.dev'); setPassword('DemoPass123!') }}>
          Use the demo account
        </button>
      </form>
      <div className="border-t pt-4 text-sm text-muted-foreground">
        Don't have an account?{' '}
        <Link to="/register" className="inline-flex items-center gap-1 font-medium text-brand hover:underline">Create one <ArrowRight className="size-3.5" /></Link>
      </div>
    </AuthLayout>
  )
}

export function RegisterPage() {
  useDocumentTitle('Create account')
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user && !busy) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (password.length < 8) return setError('Password must be at least 8 characters.')
    if (password !== confirm) return setError('Passwords do not match.')
    setBusy(true)
    setError(null)
    try {
      await register(name.trim(), email, password)
      navigate('/welcome')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout title="Create your workspace">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert variant="destructive"><AlertTriangle /><span>{error}</span></Alert>}
        <div className="space-y-1.5"><Label htmlFor="name">Name</Label><Input id="name" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" disabled={busy} /></div>
        <div className="space-y-1.5"><Label htmlFor="email">Email</Label><Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" disabled={busy} /></div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="new-password" disabled={busy} />
          <PasswordStrengthBar password={password} />
        </div>
        <div className="space-y-1.5"><Label htmlFor="confirm">Confirm password</Label><PasswordInput id="confirm" value={confirm} onChange={setConfirm} autoComplete="new-password" disabled={busy} /></div>
        <Button type="submit" className="w-full" disabled={busy}>{busy ? <Spinner /> : null}Create account</Button>
      </form>
      <div className="border-t pt-4 text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link to="/login" className="inline-flex items-center gap-1 font-medium text-brand hover:underline">Sign in <ArrowRight className="size-3.5" /></Link>
      </div>
    </AuthLayout>
  )
}

// ---------------- Onboarding (3 steps) ----------------
export function OnboardingPage() {
  useDocumentTitle('Welcome')
  const navigate = useNavigate()
  const { user } = useAuth()
  const [step, setStep] = useState(1)
  const [saved, setSaved] = useState(false)
  const [rawKey, setRawKey] = useState<string | null>(null)
  const createKey = useCreateApiKey()
  const base = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

  const generate = () => createKey.mutate(undefined, { onSuccess: (k) => setRawKey(k.key) })

  const unix = `git clone https://github.com/uh-bhinav/RedLine.git && cd RedLine\npython -m venv .venv && source .venv/bin/activate\npip install -e .\nagentbench login --base-url ${base} --api-key ${rawKey ?? '<YOUR_API_KEY>'}`
  const windows = `git clone https://github.com/uh-bhinav/RedLine.git; cd RedLine\npython -m venv .venv; .venv\\Scripts\\Activate.ps1\npip install -e .\nagentbench login --base-url ${base} --api-key ${rawKey ?? '<YOUR_API_KEY>'}`

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-2xl space-y-6 p-6 sm:p-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2"><Logo /><span className="font-semibold">Welcome{user?.name ? `, ${user.name.split(' ')[0]}` : ''}</span></div>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            Step {step} of 3
            <div className="flex gap-1.5" aria-hidden>
              {[1, 2, 3].map((i) => <span key={i} className={cn('size-2 rounded-full', i <= step ? 'bg-brand' : 'bg-muted-foreground/30')} />)}
            </div>
          </div>
        </div>

        {step === 1 && (
          <div className="space-y-4">
            <div><h2 className="text-xl font-semibold">Generate your API key</h2><p className="text-sm text-muted-foreground">The CLI and CI use this key to talk to RedLine.</p></div>
            {!rawKey ? (
              <Button onClick={generate} disabled={createKey.isPending}>{createKey.isPending && <Spinner />}Generate API key</Button>
            ) : (
              <div className="space-y-3">
                <CodeBlock code={rawKey} />
                <Alert variant="warning"><TriangleAlert /><span>This key will not be shown again. Copy it now.</span></Alert>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} className="size-4 accent-[hsl(var(--brand))]" />
                  I've saved my API key somewhere safe
                </label>
              </div>
            )}
            {createKey.error && <Alert variant="destructive"><AlertTriangle /><span>{createKey.error.message}</span></Alert>}
            <div className="flex justify-end"><Button onClick={() => setStep(2)} disabled={!saved}>Next <ArrowRight /></Button></div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div><h2 className="text-xl font-semibold">Install the CLI</h2><p className="text-sm text-muted-foreground">Install <code className="font-mono">agentbench</code> and log in with your key.</p></div>
            <Tabs defaultValue="unix">
              <TabsList><TabsTrigger value="unix">Mac / Linux</TabsTrigger><TabsTrigger value="win">Windows</TabsTrigger></TabsList>
              <TabsContent value="unix"><CodeBlock code={unix} /></TabsContent>
              <TabsContent value="win"><CodeBlock code={windows} /></TabsContent>
            </Tabs>
            <div className="flex justify-between"><Button variant="ghost" onClick={() => setStep(1)}>Back</Button><Button onClick={() => setStep(3)}>Next <ArrowRight /></Button></div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <div><h2 className="text-xl font-semibold">Run your first eval</h2><p className="text-sm text-muted-foreground">Register an agent, push a suite, and watch the gate decide.</p></div>
            <CodeBlock label="1. Register your agent" code="agentbench init --agent rag-agent --entrypoint agents.rag_agent.agent:run_turn" />
            <CodeBlock label="2. Push the eval suite" code="agentbench push-suite eval-suites/rag-agent/baseline.yaml" />
            <CodeBlock label="3. Run it" code="agentbench run --suite baseline" />
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(2)}>Back</Button>
              <Button variant="brand" onClick={() => navigate('/')}><Check />Go to dashboard</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
