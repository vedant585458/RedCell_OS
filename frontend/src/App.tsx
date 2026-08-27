import React, { lazy, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import { AppShell } from "./components/layout/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { useConnectionStore } from "./state/connectionStore";

// Code-split route components via React.lazy
const DashboardPage = lazy(() => import("./routes/DashboardPage"));
const OfficePage = lazy(() => import("./routes/OfficePage"));
const EngagementsPage = lazy(() => import("./routes/EngagementsPage"));
const ReportsPage = lazy(() => import("./routes/ReportsPage"));
const SettingsPage = lazy(() => import("./routes/SettingsPage"));
const NotFoundPage = lazy(() => import("./routes/NotFoundPage"));

export const App: React.FC = () => {
  const startPolling = useConnectionStore((state) => state.startPolling);
  const stopPolling = useConnectionStore((state) => state.stopPolling);

  useEffect(() => {
    // Start automatic backend health check polling
    const cleanup = startPolling(2000);
    return () => {
      cleanup();
      stopPolling();
    };
  }, [startPolling, stopPolling]);

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<DashboardPage />} />
              <Route path="dashboard" element={<Navigate to="/" replace />} />
              <Route path="office" element={<OfficePage />} />
              <Route path="engagements" element={<EngagementsPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
};

export default App;
