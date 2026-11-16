import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle2, Copy, RocketIcon } from "lucide-react";

export function OnboardingPage() {
  const navigate = useNavigate();
  const [copied, setCopied] = useState(false);
  const [currentStep, setCurrentStep] = useState(1);

  const cliInstallCommand = "pip install -e .";
  const cliLoginCommand = "agentbench login --base-url http://localhost:8085 --api-key YOUR_API_KEY";

  useEffect(() => {
    // Mark onboarding as seen
    localStorage.setItem("onboarding_completed", "true");
  }, []);

  function handleCopy(text: string) {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleSkip() {
    navigate("/");
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-3xl">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <RocketIcon className="h-6 w-6 text-primary" />
          </div>
          <CardTitle className="text-3xl">
            Welcome to Red<span className="text-primary">Line</span>!
          </CardTitle>
          <CardDescription>
            Let's get you started in 3 quick steps
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-8">
          {/* Step 1 */}
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground font-semibold">
                1
              </div>
              <h3 className="text-lg font-semibold">Generate an API Key</h3>
            </div>
            <div className="ml-11 space-y-2">
              <p className="text-sm text-muted-foreground">
                You'll need an API key to authenticate the CLI with RedLine.
              </p>
              <Button
                variant="outline"
                onClick={() => {
                  navigate("/");
                  // TODO: Open API key dialog once we build the settings page
                }}
              >
                Go to Settings → API Keys
              </Button>
            </div>
          </div>

          {/* Step 2 */}
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground font-semibold">
                2
              </div>
              <h3 className="text-lg font-semibold">Install the CLI</h3>
            </div>
            <div className="ml-11 space-y-2">
              <p className="text-sm text-muted-foreground">
                Install the RedLine CLI tool to register agents and run evals.
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-md bg-muted px-3 py-2 text-sm font-mono">
                  {cliInstallCommand}
                </code>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => handleCopy(cliInstallCommand)}
                >
                  {copied ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </div>

          {/* Step 3 */}
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground font-semibold">
                3
              </div>
              <h3 className="text-lg font-semibold">Create Your First Agent</h3>
            </div>
            <div className="ml-11 space-y-2">
              <p className="text-sm text-muted-foreground">
                Register your first AI agent and run an evaluation.
              </p>
              <div className="space-y-2">
                <code className="block rounded-md bg-muted px-3 py-2 text-sm font-mono">
                  agentbench init --agent my-agent
                </code>
                <code className="block rounded-md bg-muted px-3 py-2 text-sm font-mono">
                  agentbench push-suite eval-suites/my-agent/baseline.yaml
                </code>
                <code className="block rounded-md bg-muted px-3 py-2 text-sm font-mono">
                  agentbench run --suite baseline
                </code>
              </div>
            </div>
          </div>

          <div className="flex gap-3 pt-4">
            <Button variant="outline" onClick={handleSkip} className="flex-1">
              Skip for now
            </Button>
            <Button onClick={() => navigate("/")} className="flex-1">
              Go to Dashboard
            </Button>
          </div>

          <div className="text-center">
            <p className="text-sm text-muted-foreground">
              Need help?{" "}
              <a
                href="https://github.com/uh-bhinav/RedLine#quickstart"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                View the quickstart guide
              </a>
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
