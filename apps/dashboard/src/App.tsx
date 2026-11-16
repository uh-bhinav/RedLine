import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { AuthProvider } from "@/context/AuthContext";
import { queryClient } from "@/lib/queryClient";
import { AgentDetailPage } from "@/pages/AgentDetailPage";
import { AgentsListPage } from "@/pages/AgentsListPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { DiffsListPage } from "@/pages/DiffsListPage";
import { DiffViewerPage } from "@/pages/DiffViewerPage";
import { EvalRunsListPage } from "@/pages/EvalRunsListPage";
import { LoadTestReportPage } from "@/pages/LoadTestReportPage";
import { LoadTestsListPage } from "@/pages/LoadTestsListPage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { OnboardingPage } from "@/pages/OnboardingPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { RunDetailPage } from "@/pages/RunDetailPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TraceViewerPage } from "@/pages/TraceViewerPage";

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />

            {/* Authenticated but chrome-less: first-run onboarding. */}
            <Route
              path="/welcome"
              element={
                <RequireAuth>
                  <OnboardingPage />
                </RequireAuth>
              }
            />
            <Route path="/onboarding" element={<Navigate to="/welcome" replace />} />

            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              {/*
                SPA page routes MUST NOT start with a backend API prefix:
                nginx (infra/gateway.nginx.conf) and the Vite dev proxy send ANY
                path starting with /agents, /dashboard, /auth, /eval-runs,
                /eval-suites, /diff-runs, /load-runs, /mining or /ci to the API,
                so a browser refresh there would hit the API instead of the SPA.
                Hence /agent (singular), /diffs, /runs, /load-tests, /load-run.
              */}
              <Route path="/" element={<DashboardPage />} />
              <Route path="/agent" element={<AgentsListPage />} />
              <Route path="/agent/:agentId" element={<AgentDetailPage />} />
              <Route path="/runs" element={<EvalRunsListPage />} />
              <Route path="/runs/:runId" element={<RunDetailPage />} />
              <Route path="/runs/:runId/traces" element={<TraceViewerPage />} />
              <Route path="/diffs" element={<DiffsListPage />} />
              <Route path="/diffs/:diffId" element={<DiffViewerPage />} />
              <Route path="/load-tests" element={<LoadTestsListPage />} />
              <Route path="/load-run/:loadRunId" element={<LoadTestReportPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
