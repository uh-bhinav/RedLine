import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { AgentResponse, AgentVersionCreate, AgentVersionResponse } from "@/lib/types";

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export interface RegisterAgentInput {
  name: string;
  description?: string;
  /** Python entrypoint, e.g. "agents.my_agent:run". */
  entrypoint: string;
  version_label?: string;
  model_name?: string;
}

/**
 * Registers an agent (POST /agents, idempotent by name) and its first version
 * (POST /agents/{id}/versions). The browser cannot hash agent source, so the
 * content hash is derived from entrypoint + timestamp -- unique per call.
 * POST /agents accepts JWTs as well as API keys (require_api_key).
 */
export function useRegisterAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: RegisterAgentInput) => {
      const agent = await apiFetch<AgentResponse>("/agents", {
        method: "POST",
        body: JSON.stringify({ name: input.name, description: input.description || null }),
      });
      const version: AgentVersionCreate = {
        version_label: input.version_label ?? "v1",
        model_name: input.model_name ?? "unspecified",
        prompt_text: "(registered from dashboard)",
        tool_schema: [],
        content_hash: await sha256Hex(`${input.entrypoint}:${Date.now()}`),
        entrypoint: input.entrypoint,
      };
      const created = await apiFetch<AgentVersionResponse>(`/agents/${agent.id}/versions`, {
        method: "POST",
        body: JSON.stringify(version),
      });
      return { agent, version: created };
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["summary"] });
    },
  });
}
