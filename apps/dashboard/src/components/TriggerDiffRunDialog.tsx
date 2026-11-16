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
import { useCreateDiffRun } from "@/hooks/useCreateDiffRun";
import { useEvalSuites } from "@/hooks/useEvalSuites";
import type { AgentVersionSummary } from "@/lib/types";

interface TriggerDiffRunDialogProps {
  agentId: string;
  versions: AgentVersionSummary[];
}

export function TriggerDiffRunDialog({ agentId, versions }: TriggerDiffRunDialogProps) {
  const [open, setOpen] = useState(false);
  const [versionAId, setVersionAId] = useState("");
  const [versionBId, setVersionBId] = useState("");
  const [suiteId, setSuiteId] = useState("");
  const { data: suites } = useEvalSuites(open ? agentId : undefined);
  const createDiff = useCreateDiffRun();
  const navigate = useNavigate();

  async function handleTrigger() {
    if (!versionAId || !versionBId || !suiteId) return;
    const diff = await createDiff.mutateAsync({
      version_a_id: versionAId,
      version_b_id: versionBId,
      suite_id: suiteId,
    });
    setOpen(false);
    navigate(`/diffs/${diff.id}`);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">Compare Versions</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Behavioral Diff</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Version A</Label>
              <Select value={versionAId} onValueChange={setVersionAId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {versions.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.version_label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Version B</Label>
              <Select value={versionBId} onValueChange={setVersionBId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {versions.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.version_label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
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
          {createDiff.isError && (
            <p className="text-sm text-destructive">{createDiff.error.message}</p>
          )}
        </div>
        <DialogFooter>
          <Button
            onClick={handleTrigger}
            disabled={!versionAId || !versionBId || !suiteId || createDiff.isPending}
          >
            {createDiff.isPending ? "Comparing…" : "Compare"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
