import type { ReactNode } from "react";
import { Activity, GitCompareArrows, ShieldCheck } from "lucide-react";
import { Logo } from "@/components/Logo";

const BULLETS = [
  { icon: ShieldCheck, text: "Gate every release on a reliability score" },
  { icon: Activity, text: "Track error budgets and drift across agents" },
  { icon: GitCompareArrows, text: "Diff agent behaviour between versions" },
];

/** Split-screen auth layout: 40% dark brand panel + form panel (stacked on mobile). */
export function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-background md:flex-row">
      <aside className="flex flex-col justify-between gap-8 bg-slate-950 p-8 text-slate-100 md:w-[40%] md:p-12">
        <div className="flex items-center gap-3">
          <Logo size={40} />
          <span className="text-2xl font-bold tracking-tight">RedLine</span>
        </div>
        <div className="space-y-6">
          <h2 className="text-xl font-medium text-slate-300 md:text-2xl">Agent Reliability Engineering</h2>
          <ul className="space-y-4">
            {BULLETS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3 text-sm text-slate-300">
                <Icon className="mt-0.5 size-5 shrink-0 text-red-400" />
                <span>{text}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="hidden text-xs text-slate-500 md:block">Ship agents you can trust.</p>
      </aside>
      <main className="flex flex-1 items-center justify-center p-6 md:p-12">
        <div className="w-full max-w-sm space-y-6">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
