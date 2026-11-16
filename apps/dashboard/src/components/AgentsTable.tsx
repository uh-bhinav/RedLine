import { Link, useNavigate } from "react-router-dom";
import { GateBadge } from "@/components/GateBadge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AgentListItem } from "@/lib/types";
import { arsColor, cn, formatAr, timeAgo } from "@/lib/utils";

/** Agents table (Name | ARS | Gate | Last version | Last run | Registered); rows open /agent/:id. */
export function AgentsTable({ agents }: { agents: AgentListItem[] }) {
  const navigate = useNavigate();
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>ARS</TableHead>
            <TableHead>Gate</TableHead>
            <TableHead>Last version</TableHead>
            <TableHead>Last run</TableHead>
            <TableHead>Registered</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {agents.map((a) => (
            <TableRow
              key={a.id}
              className="cursor-pointer"
              onClick={() => navigate(`/agent/${a.id}`)}
            >
              <TableCell className="whitespace-nowrap font-medium">
                <Link
                  to={`/agent/${a.id}`}
                  className="hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  {a.name}
                </Link>
              </TableCell>
              <TableCell className={cn("font-mono font-semibold tabular-nums", arsColor(a.latest_ars))}>
                {formatAr(a.latest_ars)}
              </TableCell>
              <TableCell>
                <GateBadge passed={a.latest_run?.gate_passed} status={a.latest_run?.status} />
              </TableCell>
              <TableCell className="whitespace-nowrap">{a.latest_version_label ?? "—"}</TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {a.latest_run ? timeAgo(a.latest_run.completed_at) : "—"}
              </TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {new Date(a.created_at).toLocaleDateString()}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function AgentsTableSkeleton() {
  return (
    <div className="space-y-2" aria-label="Loading agents">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}
