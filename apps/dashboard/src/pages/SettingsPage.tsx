import { KeyRound, Loader2, Monitor, Moon, Plus, Sun } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { CodeBlock } from "@/components/CodeBlock";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/useApiKeys";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useTheme } from "@/hooks/useTheme";
import { cn, formatDateTime } from "@/lib/utils";

function ApiKeysTab() {
  const keys = useApiKeys();
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();
  const [freshKey, setFreshKey] = useState<string | null>(null);

  function generate() {
    const label = `Dashboard key ${new Date().toISOString().slice(0, 16).replace("T", " ")}`;
    create.mutate(
      { label },
      {
        onSuccess: (created) => {
          setFreshKey(created.key);
          toast.success("API key generated");
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">Your API Keys</CardTitle>
        <Button size="sm" onClick={generate} disabled={create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
          Generate New API Key
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {keys.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : keys.error ? (
          <ErrorCard error={keys.error} onRetry={() => void keys.refetch()} />
        ) : !keys.data || keys.data.length === 0 ? (
          <EmptyState
            icon={KeyRound}
            title="No API keys yet"
            description="Generate a key to use the CLI or CI integration."
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Key</TableHead>
                  <TableHead>Label</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {keys.data.map((k) => (
                  <TableRow key={k.id}>
                    <TableCell className="font-mono text-xs">{k.masked_key}</TableCell>
                    <TableCell className="text-muted-foreground">{k.label}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(k.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {k.revoked ? (
                        <Badge variant="secondary">Revoked</Badge>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={revoke.isPending}
                          onClick={() =>
                            revoke.mutate(k.id, { onSuccess: () => toast.success("API key revoked") })
                          }
                        >
                          Revoke
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          API keys grant full access to your tenant. Treat them like passwords. Revoke any key you no longer
          need.
        </p>
      </CardContent>

      <Dialog open={freshKey !== null} onOpenChange={(open) => !open && setFreshKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Your new API key</DialogTitle>
            <DialogDescription>Use it as a bearer token for the CLI or CI integration.</DialogDescription>
          </DialogHeader>
          {freshKey && <CodeBlock code={freshKey} />}
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
            ⚠ This key will not be shown again. Copy it now.
          </p>
          <DialogFooter>
            <Button onClick={() => setFreshKey(null)}>I have copied it</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function AppearanceTab() {
  const { theme, setTheme } = useTheme();
  const options = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
  ] as const;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Theme</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="inline-flex gap-1 rounded-lg bg-muted p-1" role="radiogroup" aria-label="Theme">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={theme === o.value}
              onClick={() => setTheme(o.value)}
              className={cn(
                "flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
                theme === o.value ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <o.icon className="size-4" />
              {o.label}
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function SettingsPage() {
  useDocumentTitle("Settings");
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">Manage API access and how RedLine looks.</p>
      </div>
      <Tabs defaultValue="keys">
        <TabsList>
          <TabsTrigger value="keys">API Keys</TabsTrigger>
          <TabsTrigger value="appearance">Appearance</TabsTrigger>
        </TabsList>
        <TabsContent value="keys">
          <ApiKeysTab />
        </TabsContent>
        <TabsContent value="appearance">
          <AppearanceTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
