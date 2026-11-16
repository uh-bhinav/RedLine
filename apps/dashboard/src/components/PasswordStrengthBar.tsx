import { cn } from "@/lib/utils";

/** 4-segment strength bar: length >= 8, uppercase, lowercase, digit/special. */
export function PasswordStrengthBar({ password }: { password: string }) {
  const checks = [
    password.length >= 8,
    /[A-Z]/.test(password),
    /[a-z]/.test(password),
    /[\d\W]/.test(password),
  ];
  const score = password ? checks.filter(Boolean).length : 0;
  const palette = ["bg-muted", "bg-red-500", "bg-orange-500", "bg-yellow-500", "bg-green-500"];
  const label = ["", "Weak", "Fair", "Good", "Strong"][score];
  return (
    <div className="space-y-1" aria-live="polite">
      <div className="flex gap-1.5">
        {[1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={cn("h-1.5 flex-1 rounded-full transition-colors", i <= score ? palette[score] : "bg-muted")}
          />
        ))}
      </div>
      <p className="h-4 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
