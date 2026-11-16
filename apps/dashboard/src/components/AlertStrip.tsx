import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface StripAlert {
  /** Stable id (e.g. `${agentId}:budget`) -- dismissal is remembered per session by id. */
  id: string;
  message: string;
  href: string;
  tone: "warn" | "bad";
}

const DISMISS_KEY = "rl_dismissed_alerts";

function readDismissed(): string[] {
  try {
    return JSON.parse(sessionStorage.getItem(DISMISS_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

/** At most 3 dismissible alert rows, or a green "no active alerts" state. */
export function AlertStrip({ alerts }: { alerts: StripAlert[] }) {
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const visible = alerts.filter((a) => !dismissed.includes(a.id)).slice(0, 3);

  function dismiss(id: string) {
    const next = [...dismissed, id];
    setDismissed(next);
    try {
      sessionStorage.setItem(DISMISS_KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable */
    }
  }

  if (visible.length === 0) {
    return (
      <Alert variant="success" className="flex items-center gap-3">
        <CheckCircle2 className="!static size-4 shrink-0" />
        <span className="text-sm font-medium">
          No active alerts — every agent is within its reliability targets.
        </span>
      </Alert>
    );
  }

  return (
    <div className="space-y-2">
      {visible.map((a) => (
        <motion.div
          key={a.id}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          className={cn(
            "flex items-center gap-3 rounded-lg border border-l-4 bg-card p-3 text-sm",
            a.tone === "bad" ? "border-l-red-500" : "border-l-amber-500",
          )}
        >
          <AlertTriangle
            className={cn("size-4 shrink-0", a.tone === "bad" ? "text-red-500" : "text-amber-500")}
          />
          <span className="flex-1">{a.message}</span>
          <Button asChild variant="link" size="sm">
            <Link to={a.href}>View →</Link>
          </Button>
          <button
            aria-label="Dismiss alert"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => dismiss(a.id)}
          >
            <X className="size-4" />
          </button>
        </motion.div>
      ))}
    </div>
  );
}
