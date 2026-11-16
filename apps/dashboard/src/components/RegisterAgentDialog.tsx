import { type FormEvent, type ReactNode, useState } from "react";
import { Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ErrorCard } from "@/components/ErrorCard";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRegisterAgent } from "@/hooks/useRegisterAgent";

/** "Register Agent" dialog; `children` is the trigger element. */
export function RegisterAgentDialog({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [entrypoint, setEntrypoint] = useState("");
  const register = useRegisterAgent();
  const navigate = useNavigate();

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) register.reset();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const { agent } = await register.mutateAsync({
        name: name.trim(),
        description: description.trim() || undefined,
        entrypoint: entrypoint.trim(),
      });
      toast.success(`Agent "${agent.name}" registered`);
      setOpen(false);
      setName("");
      setDescription("");
      setEntrypoint("");
      navigate(`/agent/${agent.id}`);
    } catch {
      /* shown inline via register.error */
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Register Agent</DialogTitle>
            <DialogDescription>Add an agent so RedLine can evaluate it.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="agent-name">Name</Label>
            <Input
              id="agent-name"
              required
              placeholder="my-agent"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="agent-desc">Description (optional)</Label>
            <Input
              id="agent-desc"
              placeholder="Customer support RAG agent"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="agent-entrypoint">Entrypoint</Label>
            <Input
              id="agent-entrypoint"
              required
              className="font-mono"
              placeholder="agents.my_agent.agent:run_turn"
              value={entrypoint}
              onChange={(e) => setEntrypoint(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Python: agents.rag_agent.agent:run_turn | HTTP: http://host/turn
            </p>
          </div>
          {register.error && <ErrorCard error={register.error} />}
          <DialogFooter>
            <Button type="submit" disabled={register.isPending || !name.trim() || !entrypoint.trim()}>
              {register.isPending && <Loader2 className="animate-spin" />}
              Register
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
