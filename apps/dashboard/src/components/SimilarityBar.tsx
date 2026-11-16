import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

/** Behaviour-similarity bar (0..1): green at/above `threshold`, red below. */
export function SimilarityBar({ value, threshold }: { value: number; threshold: number }) {
  const ok = value >= threshold;
  return (
    <div className="flex items-center gap-3">
      {/* Wrapper gives the bar a real width inside flex rows (Progress is w-full). */}
      <div className="min-w-24 max-w-56 flex-1">
        <Progress
          value={value * 100}
          className="h-2"
          indicatorClassName={ok ? "bg-green-500" : "bg-red-500"}
        />
      </div>
      <span
        className={cn(
          "shrink-0 font-mono text-sm",
          ok ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400",
        )}
      >
        {value.toFixed(3)}
      </span>
    </div>
  );
}
