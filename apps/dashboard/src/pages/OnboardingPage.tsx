import { useEffect, useState } from "react";
import { Check, Copy, KeyRound, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { CodeBlock } from "@/components/CodeBlock";
import { Logo } from "@/components/Logo";
import { ErrorCard } from "@/components/ErrorCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCreateApiKey } from "@/hooks/useApiKeys";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { cn } from "@/lib/utils";

const TOTAL_STEPS = 3;

function StepDots({ step }: { step: number }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm font-medium text-muted-foreground">
        Step {step} of {TOTAL_STEPS}
      </span>
      <div className="flex gap-2" aria-hidden>
        {[1, 2, 3].map((i) => (
          <span
            key={i}
            className={cn(
              "size-2.5 rounded-full transition-colors",
              i === step ? "bg-primary" : i < step ? "bg-primary/50" : "bg-muted",
            )}
          />
        ))}
      </div>
    </div>
  );
}

export function OnboardingPage() {
  useDocumentTitle("Welcome");
  const navigate = useNavigate();
  const createKey = useCreateApiKey();
  const [step, setStep] = useState(1);
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem("onboarding_completed", "true");
    } catch {
      /* storage unavailable */
    }
  }, []);

  const baseUrl = window.location.origin;
  const keyForCmd = rawKey ?? "<YOUR_API_KEY>";

  async function generate() {
    try {
      const created = await createKey.mutateAsync({ label: "CLI (onboarding)" });
      setRawKey(created.key);
    } catch {
      /* surfaced via createKey.error */
    }
  }

  async function copyKey() {
    if (!rawKey) return;
    try {
      await navigator.clipboard.writeText(rawKey);
      setCopied(true);
    } catch {
      /* clipboard unavailable -- user can select the key manually */
    }
  }

  const loginCmd = `agentbench login --base-url ${baseUrl} --api-key ${keyForCmd}`;
  const unixInstall = `git clone https://github.com/uh-bhinav/RedLine.git
cd RedLine
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
${loginCmd}`;
  const winInstall = `git clone https://github.com/uh-bhinav/RedLine.git
cd RedLine
python -m venv .venv
.venv\\Scripts\\activate
pip install -e .
${loginCmd}`;

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-2xl">
        <CardContent className="space-y-6 p-6 sm:p-8">
          <div className="flex items-center gap-3">
            <Logo size={32} />
            <h1 className="text-2xl font-bold">Welcome to RedLine</h1>
          </div>
          <StepDots step={step} />

          {step === 1 && (
            <section className="space-y-4">
              <h2 className="text-lg font-semibold">Generate an API key</h2>
              <p className="text-sm text-muted-foreground">
                The CLI authenticates with an API key. It is shown only once, so copy it somewhere safe.
              </p>
              {!rawKey ? (
                <div className="space-y-3">
                  {createKey.error && <ErrorCard error={createKey.error} onRetry={() => void generate()} />}
                  <Button onClick={() => void generate()} disabled={createKey.isPending}>
                    {createKey.isPending ? <Loader2 className="animate-spin" /> : <KeyRound />}
                    {createKey.isPending ? "Generating…" : "Generate API key"}
                  </Button>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="relative">
                    <pre
                      data-testid="raw-api-key"
                      className="overflow-x-auto rounded-lg border bg-muted/60 p-3 pr-12 font-mono text-[13px]"
                    >
                      {rawKey}
                    </pre>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="absolute right-1.5 top-1.5 size-8"
                      onClick={() => void copyKey()}
                      aria-label="Copy API key"
                    >
                      {copied ? <Check className="text-green-500" /> : <Copy />}
                    </Button>
                  </div>
                  {copied && (
                    <p role="status" className="text-sm font-medium text-green-600 dark:text-green-400">
                      Key copied
                    </p>
                  )}
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={saved}
                      onChange={(e) => setSaved(e.target.checked)}
                    />
                    I've saved my API key somewhere safe
                  </label>
                </div>
              )}
            </section>
          )}

          {step === 2 && (
            <section className="space-y-4">
              <h2 className="text-lg font-semibold">Install the CLI</h2>
              <p className="text-sm text-muted-foreground">
                Clone the repo, install the CLI in a virtual environment and log in with your key.
              </p>
              <Tabs defaultValue="unix">
                <TabsList>
                  <TabsTrigger value="unix">Mac / Linux</TabsTrigger>
                  <TabsTrigger value="windows">Windows</TabsTrigger>
                </TabsList>
                <TabsContent value="unix">
                  <CodeBlock code={unixInstall} />
                </TabsContent>
                <TabsContent value="windows">
                  <CodeBlock code={winInstall} />
                </TabsContent>
              </Tabs>
            </section>
          )}

          {step === 3 && (
            <section className="space-y-4">
              <h2 className="text-lg font-semibold">Create your first agent</h2>
              <p className="text-sm text-muted-foreground">
                Register an agent, push an eval suite and run it. Results appear on your dashboard.
              </p>
              <CodeBlock label="1. Initialise" code="agentbench init --agent my-agent" />
              <CodeBlock
                label="2. Push an eval suite"
                code="agentbench push-suite eval-suites/my-agent/baseline.yaml"
              />
              <CodeBlock label="3. Run it" code="agentbench run --suite baseline" />
            </section>
          )}

          <div className="flex items-center justify-between gap-3 pt-2">
            <Button
              variant="ghost"
              onClick={() => (step === 1 ? navigate("/") : setStep(step - 1))}
            >
              {step === 1 ? "Skip for now" : "Back"}
            </Button>
            {step < TOTAL_STEPS ? (
              <Button onClick={() => setStep(step + 1)} disabled={step === 1 && !(rawKey && saved)}>
                Next
              </Button>
            ) : (
              <Button onClick={() => navigate("/")}>Go to dashboard</Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
