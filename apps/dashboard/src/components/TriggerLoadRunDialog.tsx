import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateLoadRun } from "@/hooks/useLoadRuns";
import type { AgentVersionSummary } from "@/lib/types";

interface TriggerLoadRunDialogProps {
  agentId: string;
  versions: AgentVersionSummary[];
}

export function TriggerLoadRunDialog({ agentId, versions }: TriggerLoadRunDialogProps) {
  const [open, setOpen] = useState(false);
  const [versionId, setVersionId] = useState("");
  const [message, setMessage] = useState("What are your business hours?");
  const [concurrency, setConcurrency] = useState(10);
  const [durationSeconds, setDurationSeconds] = useState(30);
  const createLoadRun = useCreateLoadRun(agentId);
  const navigate = useNavigate();

  async function handleTrigger() {
    if (!versionId) return;
    let run;
    try {
      run = await createLoadRun.mutateAsync({
        agent_version_id: versionId,
        message,
        concurrency,
        duration_seconds: durationSeconds,
        triggered_by: "manual",
      });
    } catch {
      return; // error already surfaced via the global mutation toast + inline message
    }
    setOpen(false);
    toast.success("Load test started");
    navigate(`/load-run/${run.id}`);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">Load</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Trigger Load Test</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>Agent version</Label>
            <Select value={versionId} onValueChange={setVersionId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a version" />
              </SelectTrigger>
              <SelectContent>
                {versions.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.version_label} ({v.model_name})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Message</Label>
            <Input value={message} onChange={(e) => setMessage(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Concurrency (virtual users)</Label>
              <Input
                type="number"
                min={1}
                max={1000}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label>Duration (seconds)</Label>
              <Input
                type="number"
                min={1}
                max={3600}
                value={durationSeconds}
                onChange={(e) => setDurationSeconds(Number(e.target.value))}
              />
            </div>
          </div>
          {createLoadRun.isError && (
            <p className="text-sm text-destructive">{createLoadRun.error.message}</p>
          )}
        </div>
        <DialogFooter>
          <Button onClick={handleTrigger} disabled={!versionId || createLoadRun.isPending}>
            {createLoadRun.isPending ? "Triggering…" : "Trigger"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
