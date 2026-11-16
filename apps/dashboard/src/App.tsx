import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { AuthProvider } from "@/context/AuthContext";
import { queryClient } from "@/lib/queryClient";
import { AgentDetailPage } from "@/pages/AgentDetailPage";
import { AgentsListPage } from "@/pages/AgentsListPage";
import { DiffViewerPage } from "@/pages/DiffViewerPage";
import { FailureClustersPage } from "@/pages/FailureClustersPage";
import { LoadTestReportPage } from "@/pages/LoadTestReportPage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { RunDetailPage } from "@/pages/RunDetailPage";
import { TraceViewerPage } from "@/pages/TraceViewerPage";

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              {/*
                Singular SPA page routes (/agent, /load-run), deliberately
                distinct from the plural backend API prefixes (/agents,
                /load-runs) they'd otherwise collide with at the gateway:
                nginx's prefix-location matching sends ANY path starting with
                /agents to agent_service (even GET /agents/<uuid>, which the
                backend doesn't even implement), so a browser refresh on the
                agent-detail page would 404 against the API instead of
                serving the SPA. Confirmed by testing the built gateway image
                for real, not assumed. /runs and /diffs don't collide with
                any backend prefix (/eval-runs, /diff-runs) and are left as-is.
              */}
              <Route path="/" element={<AgentsListPage />} />
              <Route path="/agent/:agentId" element={<AgentDetailPage />} />
              <Route path="/agent/:agentId/clusters" element={<FailureClustersPage />} />
              <Route path="/runs/:runId" element={<RunDetailPage />} />
              <Route path="/diffs/:diffId" element={<DiffViewerPage />} />
              <Route path="/load-run/:loadRunId" element={<LoadTestReportPage />} />
              <Route path="/runs/:runId/traces" element={<TraceViewerPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
