import { KeyRound, Monitor, Moon, Plus, Sun, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { CodeBlock, EmptyState, ErrorCard } from '@/components/shared'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, Badge, Skeleton, Spinner } from '@/components/ui/misc'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Tabs, TabsContent, TabsList, TabsTrigger,
} from '@/components/ui/overlay'
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/hooks/queries'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useTheme, type Theme } from '@/lib/theme'
import { cn, timeAgo } from '@/lib/utils'

function ApiKeysTab() {
  const keys = useApiKeys()
  const create = useCreateApiKey()
  const revoke = useRevokeApiKey()
  const [fresh, setFresh] = useState<string | null>(null)

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Your API Keys</CardTitle>
        <Button variant="brand" size="sm" disabled={create.isPending}
          onClick={() => create.mutate(undefined, { onSuccess: (k) => setFresh(k.key), onError: (e) => toast.error(e.message) })}>
          {create.isPending ? <Spinner /> : <Plus />}Generate New API Key
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {keys.isLoading ? <Skeleton className="h-24" /> : keys.error ? <ErrorCard error={keys.error} onRetry={() => keys.refetch()} />
          : !keys.data?.length ? <EmptyState icon={KeyRound} title="No API keys yet" description="Generate a key to use the CLI or CI integration." />
          : (
            <div className="divide-y rounded-lg border">
              {keys.data.map((k) => (
                <div key={k.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                  <span className="font-mono">{k.masked_key}</span>
                  <span className="flex-1 text-muted-foreground">{k.revoked ? <Badge variant="secondary">Revoked</Badge> : `Created ${timeAgo(k.created_at)}`}</span>
                  {!k.revoked && (
                    <Button size="sm" variant="outline" disabled={revoke.isPending}
                      onClick={() => revoke.mutate(k.id, { onSuccess: () => toast.success('API key revoked'), onError: (e) => toast.error(e.message) })}>Revoke</Button>
                  )}
                </div>
              ))}
            </div>
          )}
        <p className="text-xs text-muted-foreground">API keys grant full access to your tenant. Treat them like passwords. Revoke any key you no longer need.</p>
      </CardContent>

      <Dialog open={fresh !== null} onOpenChange={(o) => !o && setFresh(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Your new API key</DialogTitle><DialogDescription>Copy it now — this is the only time it is shown.</DialogDescription></DialogHeader>
          {fresh && <CodeBlock code={fresh} />}
          <Alert variant="warning"><TriangleAlert /><span>This key will not be shown again. Copy it now.</span></Alert>
          <DialogFooter><Button onClick={() => setFresh(null)}>I've copied it</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function AppearanceTab() {
  const { theme, setTheme } = useTheme()
  const opts: { value: Theme; label: string; icon: typeof Sun }[] = [
    { value: 'light', label: 'Light', icon: Sun }, { value: 'dark', label: 'Dark', icon: Moon }, { value: 'system', label: 'System', icon: Monitor },
  ]
  return (
    <Card>
      <CardHeader><CardTitle>Theme</CardTitle></CardHeader>
      <CardContent>
        <div className="inline-flex gap-1 rounded-lg bg-muted p-1" role="radiogroup" aria-label="Theme">
          {opts.map((o) => (
            <button key={o.value} role="radio" aria-checked={theme === o.value} onClick={() => setTheme(o.value)}
              className={cn('flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium transition-colors', theme === o.value ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
              <o.icon className="size-4" />{o.label}
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default function SettingsPage() {
  useDocumentTitle('Settings')
  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-bold">Settings</h1><p className="text-sm text-muted-foreground">Manage API access and how RedLine looks.</p></div>
      <Tabs defaultValue="keys">
        <TabsList><TabsTrigger value="keys">API Keys</TabsTrigger><TabsTrigger value="appearance">Appearance</TabsTrigger></TabsList>
        <TabsContent value="keys"><ApiKeysTab /></TabsContent>
        <TabsContent value="appearance"><AppearanceTab /></TabsContent>
      </Tabs>
    </div>
  )
}
