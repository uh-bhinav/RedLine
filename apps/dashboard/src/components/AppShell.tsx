import { LogOut } from "lucide-react";
import { Link, Outlet, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <Link to="/" className="text-lg font-semibold">
          Red<span className="text-primary">Line</span>
        </Link>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          {user && (
            <span>
              {user.email ?? "API key"} <span className="text-xs">({user.role})</span>
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={handleLogout}>
            <LogOut className="mr-1 h-4 w-4" />
            Log out
          </Button>
        </div>
      </header>
      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
