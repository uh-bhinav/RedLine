import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface SummaryCardProps {
  icon: LucideIcon;
  label: string;
  /** Numeric value -> CountUp animation. Ignored when `text` is given. */
  value?: number;
  decimals?: number;
  suffix?: string;
  /** Static text instead of a number (e.g. "No runs yet", "3/5"). */
  text?: string;
  tone?: "default" | "good" | "warn" | "bad";
  sub?: string;
  /** Position in the grid -- staggers the mount animation. */
  index?: number;
}

const TONE: Record<NonNullable<SummaryCardProps["tone"]>, string> = {
  default: "",
  good: "text-green-600 dark:text-green-400",
  warn: "text-amber-600 dark:text-amber-400",
  bad: "text-red-600 dark:text-red-400",
};

export function SummaryCard({
  icon: Icon,
  label,
  value,
  decimals = 0,
  suffix,
  text,
  tone = "default",
  sub,
  index = 0,
}: SummaryCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.3 }}
    >
      <Card className="p-5">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{label}</span>
          <Icon className="size-4" />
        </div>
        <div className={cn("mt-2 text-3xl font-bold tabular-nums", TONE[tone])}>
          {text ?? <AnimatedNumber value={value ?? 0} decimals={decimals} suffix={suffix} />}
        </div>
        {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
      </Card>
    </motion.div>
  );
}
