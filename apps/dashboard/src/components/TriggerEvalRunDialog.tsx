import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateEvalRun } from "@/hooks/useCreateEvalRun";
import { useEvalSuites } from "@/hooks/useEvalSuites";
import type { AgentVersionSummary } from "@/lib/types";

interface TriggerEvalRunDialogProps {
  agentId: string;
  versions: AgentVersionSummary[];
}

export function TriggerEvalRunDialog({ agentId, versions }: TriggerEvalRunDialogProps) {
  const [open, setOpen] = useState(false);
  const [versionId, setVersionId] = useState<string>("");
  const [suiteId, setSuiteId] = useState<string>("");
  const { data: suites } = useEvalSuites(open ? agentId : undefined);
  const createRun = useCreateEvalRun(agentId);
  const navigate = useNavigate();

  async function handleTrigger() {
    if (!versionId || !suiteId) return;
    const run = await createRun.mutateAsync({
      agent_version_id: versionId,
      suite_id: suiteId,
      triggered_by: "manual",
    });
    setOpen(false);
    navigate(`/runs/${run.id}`);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>Trigger Eval Run</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Trigger Eval Run</DialogTitle>
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
            <Label>Suite</Label>
            <Select value={suiteId} onValueChange={setSuiteId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a suite" />
              </SelectTrigger>
              <SelectContent>
                {suites?.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name} ({s.case_count} cases)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {createRun.isError && (
            <p className="text-sm text-destructive">{createRun.error.message}</p>
          )}
        </div>
        <DialogFooter>
          <Button
            onClick={handleTrigger}
            disabled={!versionId || !suiteId || createRun.isPending}
          >
            {createRun.isPending ? "Triggering…" : "Trigger"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
