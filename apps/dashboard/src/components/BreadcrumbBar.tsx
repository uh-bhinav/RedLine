import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import type { AgentDetailResponse, RunDetailResponse } from "@/lib/types";
import { shortId } from "@/lib/utils";

interface Crumb {
  label: string;
  to?: string;
}

/**
 * Derives breadcrumbs from the route; agent/run names come from the React
 * Query cache (no extra fetch). Subscribes to the query cache so names replace
 * ids once the page's own query resolves.
 */
export function BreadcrumbBar() {
  const { pathname } = useLocation();
  const qc = useQueryClient();
  const [, tick] = useState(0);
  useEffect(
    () => qc.getQueryCache().subscribe(() => queueMicrotask(() => tick((n) => n + 1))),
    [qc],
  );

  const seg = pathname.split("/").filter(Boolean);
  const id = seg[1] ?? "";
  let items: Crumb[] = [{ label: "Dashboard" }];

  if (seg[0] === "agent" && !id) {
    items = [{ label: "Agents" }];
  } else if (seg[0] === "agent") {
    const name = qc.getQueryData<AgentDetailResponse>(["agent", id])?.name;
    items = [
      { label: "Agents", to: "/agent" },
      { label: name ?? shortId(id), to: seg[2] ? `/agent/${id}` : undefined },
    ];
  } else if (seg[0] === "runs" && !id) {
    items = [{ label: "Eval Runs" }];
  } else if (seg[0] === "runs") {
    const run = qc.getQueryData<RunDetailResponse>(["run", id]);
    items = [
      { label: "Agents", to: "/agent" },
      ...(run?.agent_name
        ? [{ label: run.agent_name, to: run.agent_id ? `/agent/${run.agent_id}` : undefined }]
        : []),
      { label: `Run ${shortId(id)}`, to: seg[2] ? `/runs/${id}` : undefined },
      ...(seg[2] === "traces" ? [{ label: "Traces" }] : []),
    ];
  } else if (seg[0] === "diffs" && !id) {
    items = [{ label: "Diffs" }];
  } else if (seg[0] === "diffs") {
    items = [{ label: "Diffs", to: "/diffs" }, { label: shortId(id) }];
  } else if (seg[0] === "load-tests") {
    items = [{ label: "Load Tests" }];
  } else if (seg[0] === "load-run") {
    items = [{ label: "Load Tests", to: "/load-tests" }, { label: shortId(id) }];
  } else if (seg[0] === "settings") {
    items = [{ label: "Settings" }];
  }

  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
      {items.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />}
          {c.to && i < items.length - 1 ? (
            <Link to={c.to} className="truncate text-muted-foreground hover:text-foreground">
              {c.label}
            </Link>
          ) : (
            <span className="truncate font-medium">{c.label}</span>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
