import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** ARS health boundaries: >= 0.9 healthy, 0.7-0.9 at risk, < 0.7 critical. */
export const ARS_TARGET = 0.9;
export const ARS_WARN = 0.7;
/** p95 latency SLO (ms) drawn on load-test charts. */
export const P95_SLO_MS = 200;

export function arsColor(ars: number | null | undefined): string {
  if (ars == null) return "text-muted-foreground";
  if (ars >= ARS_TARGET) return "text-green-600 dark:text-green-400";
  if (ars >= ARS_WARN) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

/** CSS colour (usable in SVG fill/stroke) for an ARS value. */
export function arsHex(ars: number | null | undefined): string {
  if (ars == null) return "hsl(215 16% 55%)";
  if (ars >= ARS_TARGET) return "hsl(var(--gate-pass))";
  if (ars >= ARS_WARN) return "hsl(var(--gate-pending))";
  return "hsl(var(--gate-fail))";
}

export function arsLabel(ars: number | null | undefined): string {
  if (ars == null) return "—";
  if (ars >= ARS_TARGET) return "Healthy";
  if (ars >= ARS_WARN) return "At Risk";
  return "Critical";
}

export function formatAr(ars: number | null | undefined): string {
  if (ars == null) return "—";
  return ars.toFixed(3);
}

export const shortId = (id: string) => id.slice(0, 8);

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 45) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatCost(usd: number | null | undefined): string {
  if (usd == null) return "—";
  return usd < 0.01 ? `$${usd.toFixed(6)}` : `$${usd.toFixed(2)}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return `${Math.round(ms)}ms`;
}

export function formatPct(fraction: number | null | undefined, digits = 0): string {
  if (fraction == null) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** Active (still-progressing) run statuses -- pages poll while these hold. */
export const ACTIVE_STATUSES = new Set(["pending", "running"]);
