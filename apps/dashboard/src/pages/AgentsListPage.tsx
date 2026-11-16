import { useMemo, useState } from "react";
import { Bot, Plus, Search } from "lucide-react";
import { AgentsTable, AgentsTableSkeleton } from "@/components/AgentsTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { RegisterAgentDialog } from "@/components/RegisterAgentDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAgents } from "@/hooks/useAgents";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import type { AgentListItem } from "@/lib/types";
import { cn } from "@/lib/utils";

type GateFilter = "all" | "pass" | "fail" | "none";

const FILTERS: { value: GateFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pass", label: "PASS" },
  { value: "fail", label: "FAIL" },
  { value: "none", label: "No Runs" },
];

function matches(a: AgentListItem, f: GateFilter): boolean {
  const g = a.latest_run?.gate_passed;
  if (f === "pass") return g === true;
  if (f === "fail") return g === false;
  if (f === "none") return g == null;
  return true;
}

export function AgentsListPage() {
  useDocumentTitle("Agents");
  const { data: agents, isLoading, error, refetch } = useAgents();
  const [filter, setFilter] = useState<GateFilter>("all");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (agents ?? []).filter((a) => matches(a, filter) && (!q || a.name.toLowerCase().includes(q)));
  }, [agents, filter, query]);

  const registerButton = (
    <RegisterAgentDialog>
      <Button>
        <Plus />
        Register Agent
      </Button>
    </RegisterAgentDialog>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Agents</h1>
        {registerButton}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Filter by gate status" className="inline-flex rounded-lg border bg-muted/40 p-1">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={cn(
                "rounded-md px-3 py-1 text-sm font-medium transition-colors",
                filter === f.value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search agents by name"
            placeholder="Search by name"
            className="pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {isLoading ? (
        <AgentsTableSkeleton />
      ) : error ? (
        <ErrorCard error={error} onRetry={() => void refetch()} />
      ) : agents && agents.length === 0 ? (
        <div className="rounded-lg border">
          <EmptyState
            icon={Bot}
            title="No agents registered yet"
            description="Register an agent to start evaluating it."
            action={registerButton}
          />
        </div>
      ) : filtered.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">No agents match your filters.</p>
      ) : (
        <AgentsTable agents={filtered} />
      )}
    </div>
  );
}
