import { motion, useReducedMotion } from "framer-motion";
import {
  Bot,
  GitCompare,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PlayCircle,
  Settings,
  Sun,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { BreadcrumbBar } from "@/components/BreadcrumbBar";
import { Logo } from "@/components/Logo";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

// SPA routes avoid the /agents prefix (gateway + Vite proxy treat it as API):
// the agents section lives at /agent.
const NAV: { to: string; label: string; icon: LucideIcon; match: (p: string) => boolean }[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, match: (p) => p === "/" },
  { to: "/agent", label: "Agents", icon: Bot, match: (p) => p === "/agent" || p.startsWith("/agent/") },
  { to: "/runs", label: "Eval Runs", icon: PlayCircle, match: (p) => p.startsWith("/runs") },
  { to: "/load-tests", label: "Load Tests", icon: Zap, match: (p) => p.startsWith("/load-") },
  { to: "/diffs", label: "Diffs", icon: GitCompare, match: (p) => p.startsWith("/diffs") },
];

const COLLAPSE_KEY = "rl_sidebar_collapsed";

function NavItem({
  to,
  label,
  icon: Icon,
  active,
  collapsed,
  onNavigate,
}: {
  to: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const link = (
    <Link
      to={to}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? label : undefined}
      className={cn(
        "flex items-center gap-3 border-l-2 px-3 py-2 text-sm transition-colors",
        collapsed && "justify-center px-0",
        active
          ? "border-brand bg-brand/5 font-medium text-foreground"
          : "border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span>{label}</span>}
    </Link>
  );
  if (!collapsed) return link;
  return (
    <Tooltip delayDuration={150}>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

function Sidebar({
  collapsed,
  onToggle,
  onNavigate,
}: {
  collapsed: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
}) {
  const { pathname } = useLocation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const initials = (user?.email ?? "?").slice(0, 2).toUpperCase();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <aside
      className={cn(
        "flex h-full flex-col border-r bg-card transition-[width] duration-200",
        collapsed ? "w-14" : "w-60",
      )}
    >
      <div
        className={cn(
          "flex h-14 items-center border-b px-3",
          collapsed ? "justify-center" : "justify-between",
        )}
      >
        <Link to="/" className="flex items-center gap-2" onClick={onNavigate} aria-label="RedLine home">
          <Logo />
          {!collapsed && <span className="text-lg font-bold tracking-tight">RedLine</span>}
        </Link>
        {onToggle && !collapsed && (
          <Button variant="ghost" size="icon" className="size-8" onClick={onToggle} aria-label="Collapse sidebar">
            <PanelLeftClose />
          </Button>
        )}
      </div>
      {onToggle && collapsed && (
        <Button variant="ghost" size="icon" className="mx-auto mt-2 size-8" onClick={onToggle} aria-label="Expand sidebar">
          <PanelLeftOpen />
        </Button>
      )}

      <nav className="mt-3 flex flex-1 flex-col gap-0.5" aria-label="Main">
        {NAV.map((n) => (
          <NavItem key={n.to} {...n} active={n.match(pathname)} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </nav>

      <div className="border-t py-2">
        <NavItem
          to="/settings"
          label="Settings"
          icon={Settings}
          active={pathname.startsWith("/settings")}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              aria-label="Account menu"
              className={cn(
                "mt-1 flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/50",
                collapsed && "justify-center px-0",
              )}
            >
              <Avatar>
                <AvatarFallback>{initials}</AvatarFallback>
              </Avatar>
              {!collapsed && (
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{user?.email ?? "API key"}</span>
                  <span className="block truncate text-xs text-muted-foreground">{user?.tenant_name}</span>
                </span>
              )}
              {!collapsed && user && (
                <Badge variant="info" className="capitalize">
                  {user.role}
                </Badge>
              )}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start">
            <DropdownMenuLabel>{user?.email ?? "API key"}</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => void handleLogout()}>
              <LogOut />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  );
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const { resolved, setTheme } = useTheme();
  const { pathname } = useLocation();
  const reduceMotion = useReducedMotion();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [pathname]);

  function toggle() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
  }

  return (
    <TooltipProvider>
      <div className="flex h-screen overflow-hidden">
        <div className="hidden md:block">
          <Sidebar collapsed={collapsed} onToggle={toggle} />
        </div>

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent aria-describedby={undefined}>
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <SheetDescription className="sr-only">Main navigation</SheetDescription>
            <Sidebar collapsed={false} onNavigate={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>

        <main className="flex flex-1 flex-col overflow-hidden">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card/60 px-4 backdrop-blur">
            <Button
              variant="ghost"
              size="icon"
              className="size-8 md:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
            >
              <Menu />
            </Button>
            <div className="min-w-0 flex-1">
              <BreadcrumbBar />
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="size-8"
              onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
              aria-label="Toggle theme"
            >
              {resolved === "dark" ? <Sun /> : <Moon />}
            </Button>
          </header>
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 md:p-8">
            <motion.div
              key={pathname}
              initial={reduceMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: reduceMotion ? 0 : 0.2 }}
              className="mx-auto max-w-7xl"
            >
              <Outlet />
            </motion.div>
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
