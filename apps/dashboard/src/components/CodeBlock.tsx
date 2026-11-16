import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Monospace block with a copy-to-clipboard button. */
export function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="relative">
      {label && <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>}
      <pre className="overflow-x-auto rounded-lg border bg-muted/60 p-3 pr-12 font-mono text-[13px] leading-relaxed">
        {code}
      </pre>
      <Button
        size="icon"
        variant="ghost"
        className={cn("absolute right-1.5 size-8", label ? "top-6" : "top-1.5")}
        onClick={copy}
        aria-label="Copy to clipboard"
      >
        {copied ? <Check className="text-green-500" /> : <Copy />}
      </Button>
    </div>
  );
}
