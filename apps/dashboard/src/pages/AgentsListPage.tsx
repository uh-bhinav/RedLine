import { Link } from "react-router-dom";
import { GateResultBanner } from "@/components/GateResultBanner";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAgents } from "@/hooks/useAgents";

export function AgentsListPage() {
  const { data: agents, isLoading, error } = useAgents();

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-destructive">Failed to load agents: {error.message}</p>;
  }

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Agents</h1>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Latest version</TableHead>
            <TableHead>Latest run</TableHead>
            <TableHead>Registered</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {agents?.map((agent) => (
            <TableRow key={agent.id} className="cursor-pointer">
              <TableCell className="font-medium">
                <Link to={`/agent/${agent.id}`} className="hover:underline">
                  {agent.name}
                </Link>
              </TableCell>
              <TableCell className="text-muted-foreground">{agent.description ?? "—"}</TableCell>
              <TableCell>{agent.latest_version_label ?? "—"}</TableCell>
              <TableCell>
                {agent.latest_run ? (
                  <Link to={`/runs/${agent.latest_run.id}`}>
                    <GateResultBanner
                      variant="badge"
                      status={agent.latest_run.status}
                      gateResult={
                        agent.latest_run.gate_passed === null
                          ? null
                          : { passed: agent.latest_run.gate_passed, reasons: [] }
                      }
                    />
                  </Link>
                ) : (
                  <span className="text-muted-foreground">No runs yet</span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {new Date(agent.created_at).toLocaleDateString()}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {agents?.length === 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">
          No agents registered yet.
        </p>
      )}
    </div>
  );
}
