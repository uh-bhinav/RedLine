import type { ReactNode } from "react";
import { useAuth } from "@/context/AuthContext";
import type { Role } from "@/lib/types";

/**
 * Client-side UX hiding ONLY -- the real enforcement is `require_tenant_role`
 * server-side (apps/api/core/security.py). Hiding a button here does not
 * protect anything; it just avoids showing a viewer a button that would 403.
 */
export function RoleGate({ allow, children }: { allow: Role[]; children: ReactNode }) {
  const { role } = useAuth();
  if (role === null || !allow.includes(role)) return null;
  return <>{children}</>;
}
