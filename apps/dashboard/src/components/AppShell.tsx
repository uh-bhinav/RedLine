import { useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Bot, ChevronRight, GitCompare, LayoutDashboard, LogOut, Menu, Moon, PanelLeftClose, PanelLeftOpen,
  PlayCircle, Settings, Sun, Zap, type LucideIcon,
} from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Logo } from '@/components/shared'
import { Badge } from '@/components/ui/misc'
import { Button } from '@/components/ui/button'
import {
  Avatar, AvatarFallback, Dialog, DialogContent, DialogDescription, DialogTitle, DropdownMenu, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger, Tip, TooltipProvider,
} from '@/components/ui/overlay'
import { useAuth } from '@/lib/auth'
import { useTheme } from '@/lib/theme'
import type { AgentDetail, LoadRun, RunDetail } from '@/lib/types'
import { cn, shortId } from '@/lib/utils'

const NAV: { to: string; label: string; icon: LucideIcon; match: (p: string) => boolean }[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, match: (p) => p === '/' },
  { to: '/agents', label: 'Agents', icon: Bot, match: (p) => p.startsWith('/agents') || p.startsWith('/agent/') },
  { to: '/runs', label: 'Eval Runs', icon: PlayCircle, match: (p) => p.startsWith('/runs') },
  { to: '/load-tests', label: 'Load Tests', icon: Zap, match: (p) => p.startsWith('/load') },
  { to: '/diffs', label: 'Diffs', icon: GitCompare, match: (p) => p.startsWith('/diffs') },
]

const COLLAPSE_KEY = 'rl_sidebar_collapsed'

function NavItem({ to, label, icon: Icon, active, collapsed, onNavigate }: {
  to: string; label: string; icon: LucideIcon; active: boolean; collapsed: boolean; onNavigate?: () => void
}) {
  const link = (
    <Link
      to={to}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex items-center gap-3 border-l-2 px-3 py-2 text-sm transition-colors',
        collapsed && 'justify-center px-0',
        active
          ? 'border-brand bg-brand/5 font-medium text-foreground'
          : 'border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground',
      )}
    >
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span>{label}</span>}
    </Link>
  )
  return collapsed ? <Tip label={label}>{link}</Tip> : link
}

function Sidebar({ collapsed, onToggle, onNavigate }: { collapsed: boolean; onToggle?: () => void; onNavigate?: () => void }) {
  const { pathname } = useLocation()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const initials = (user?.name ?? user?.email ?? '?').slice(0, 2).toUpperCase()

  return (
    <aside className={cn('flex h-full flex-col border-r bg-card transition-[width] duration-200', collapsed ? 'w-14' : 'w-60')}>
      <div className={cn('flex h-14 items-center border-b px-3', collapsed ? 'justify-center' : 'justify-between')}>
        <Link to="/" className="flex items-center gap-2" onClick={onNavigate}>
          <Logo />
          {!collapsed && <span className="text-lg font-bold tracking-tight">RedLine</span>}
        </Link>
        {onToggle && !collapsed && (
          <Button variant="ghost" size="icon" className="size-8" onClick={onToggle} aria-label="Collapse sidebar"><PanelLeftClose /></Button>
        )}
      </div>
      {onToggle && collapsed && (
        <Button variant="ghost" size="icon" className="mx-auto mt-2 size-8" onClick={onToggle} aria-label="Expand sidebar"><PanelLeftOpen /></Button>
      )}

      <nav className="mt-3 flex flex-1 flex-col gap-0.5" aria-label="Main">
        {NAV.map((n) => (
          <NavItem key={n.to} {...n} active={n.match(pathname)} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </nav>

      <div className="border-t py-2">
        <NavItem to="/settings" label="Settings" icon={Settings} active={pathname.startsWith('/settings')} collapsed={collapsed} onNavigate={onNavigate} />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className={cn('mt-1 flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/50', collapsed && 'justify-center px-0')}>
              <Avatar><AvatarFallback>{initials}</AvatarFallback></Avatar>
              {!collapsed && (
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{user?.name ?? 'Account'}</span>
                  <span className="block truncate text-xs text-muted-foreground">{user?.email}</span>
                </span>
              )}
              {!collapsed && user && <Badge variant="info" className="capitalize">{user.role}</Badge>}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start">
            <DropdownMenuLabel>{user?.email}</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => { logout(); navigate('/login') }}><LogOut />Log out</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  )
}

function Crumb({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
      {items.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />}
          {c.to && i < items.length - 1
            ? <Link to={c.to} className="truncate text-muted-foreground hover:text-foreground">{c.label}</Link>
            : <span className="truncate font-medium">{c.label}</span>}
        </Fragment>
      ))}
    </nav>
  )
}

/** Derives breadcrumbs from the route; names come from the React Query cache (no extra fetch). */
function BreadcrumbBar() {
  const { pathname } = useLocation()
  const qc = useQueryClient()
  // Re-render when the cache fills so names replace ids once the page's own query resolves.
  const [, tick] = useState(0)
  useEffect(() => qc.getQueryCache().subscribe(() => queueMicrotask(() => tick((n) => n + 1))), [qc])
  const seg = pathname.split('/').filter(Boolean)
  const id = seg[1] ?? ''

  const agentName = (agentId: string) => qc.getQueryData<AgentDetail>(['agent', agentId])?.name
  let items: { label: string; to?: string }[] = [{ label: 'Dashboard' }]

  if (seg[0] === 'agents') items = [{ label: 'Agents' }]
  else if (seg[0] === 'agent')
    items = [{ label: 'Agents', to: '/agents' }, { label: agentName(id) ?? shortId(id) }]
  else if (seg[0] === 'runs' && !id) items = [{ label: 'Eval Runs' }]
  else if (seg[0] === 'runs') {
    const run = qc.getQueryData<RunDetail>(['run', id])
    items = [
      { label: 'Agents', to: '/agents' },
      { label: run?.agent_name ?? '…', to: run ? `/agent/${run.agent_id}` : undefined },
      { label: `Run ${shortId(id)}`, to: seg[2] ? `/runs/${id}` : undefined },
      ...(seg[2] === 'traces' ? [{ label: 'Traces' }] : []),
    ]
  } else if (seg[0] === 'diffs' && !id) items = [{ label: 'Diffs' }]
  else if (seg[0] === 'diffs') items = [{ label: 'Diffs', to: '/diffs' }, { label: shortId(id) }]
  else if (seg[0] === 'load-tests') items = [{ label: 'Load Tests' }]
  else if (seg[0] === 'load-run') {
    const load = qc.getQueryData<LoadRun>(['load', id])
    items = [{ label: 'Load Tests', to: '/load-tests' }, { label: load ? `${load.agent_name} · ${shortId(id)}` : shortId(id) }]
  } else if (seg[0] === 'settings') items = [{ label: 'Settings' }]
  return <Crumb items={items} />
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const { resolved, setTheme } = useTheme()
  const { pathname } = useLocation()

  const toggle = () => {
    setCollapsed((c) => {
      try { localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1') } catch { /* storage unavailable */ }
      return !c
    })
  }

  return (
    <TooltipProvider>
      <div className="flex h-screen overflow-hidden">
        <div className="hidden md:block"><Sidebar collapsed={collapsed} onToggle={toggle} /></div>

        <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
          <DialogContent side="left" hideClose aria-describedby={undefined}>
            <DialogTitle className="sr-only">Navigation</DialogTitle>
            <DialogDescription className="sr-only">Main navigation</DialogDescription>
            <Sidebar collapsed={false} onNavigate={() => setMobileOpen(false)} />
          </DialogContent>
        </Dialog>

        <main className="flex flex-1 flex-col overflow-hidden">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card/60 px-4 backdrop-blur">
            <Button variant="ghost" size="icon" className="size-8 md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu /></Button>
            <div className="min-w-0 flex-1"><BreadcrumbBar /></div>
            <Button variant="ghost" size="icon" className="size-8" onClick={() => setTheme(resolved === 'dark' ? 'light' : 'dark')} aria-label="Toggle theme">
              {resolved === 'dark' ? <Sun /> : <Moon />}
            </Button>
          </header>
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 md:p-8">
            <motion.div key={pathname} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="mx-auto max-w-7xl">
              <Outlet />
            </motion.div>
          </div>
        </main>
      </div>
    </TooltipProvider>
  )
}
