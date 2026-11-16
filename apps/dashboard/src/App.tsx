import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { Spinner } from '@/components/ui/misc'
import { useAuth } from '@/lib/auth'
import AgentDetailPage from '@/pages/AgentDetailPage'
import AgentsListPage from '@/pages/AgentsListPage'
import { LoginPage, OnboardingPage, RegisterPage } from '@/pages/auth'
import DashboardPage from '@/pages/DashboardPage'
import DiffViewerPage from '@/pages/DiffViewerPage'
import LoadTestReportPage from '@/pages/LoadTestReportPage'
import { DiffsListPage, EvalRunsListPage, LoadTestsListPage } from '@/pages/lists'
import RunDetailPage from '@/pages/RunDetailPage'
import SettingsPage from '@/pages/SettingsPage'
import TraceViewerPage from '@/pages/TraceViewerPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading)
    return <div className="flex h-screen items-center justify-center"><Spinner className="size-6" /></div>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

function NotFound() {
  return (
    <div className="py-24 text-center">
      <h1 className="text-4xl font-bold">404</h1>
      <p className="mt-2 text-muted-foreground">That page doesn't exist.</p>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/welcome" element={<RequireAuth><OnboardingPage /></RequireAuth>} />
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/agents" element={<AgentsListPage />} />
        <Route path="/agent/:id" element={<AgentDetailPage />} />
        <Route path="/runs" element={<EvalRunsListPage />} />
        <Route path="/runs/:id" element={<RunDetailPage />} />
        <Route path="/runs/:id/traces" element={<TraceViewerPage />} />
        <Route path="/load-tests" element={<LoadTestsListPage />} />
        <Route path="/load-run/:id" element={<LoadTestReportPage />} />
        <Route path="/diffs" element={<DiffsListPage />} />
        <Route path="/diffs/:id" element={<DiffViewerPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
