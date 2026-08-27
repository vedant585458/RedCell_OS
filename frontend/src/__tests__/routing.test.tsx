import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import DashboardPage from "../routes/DashboardPage";
import OfficePage from "../routes/OfficePage";
import EngagementsPage from "../routes/EngagementsPage";
import ReportsPage from "../routes/ReportsPage";
import SettingsPage from "../routes/SettingsPage";
import NotFoundPage from "../routes/NotFoundPage";
import { useConnectionStore } from "../state/connectionStore";

function renderWithRouter(initialEntry = "/") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Suspense fallback={<div>Loading...</div>}>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="office" element={<OfficePage />} />
            <Route path="engagements" element={<EngagementsPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </Suspense>
    </MemoryRouter>
  );
}

describe("AppShell and Route Navigation", () => {
  beforeEach(() => {
    useConnectionStore.getState().reset();
  });

  it("renders DashboardPage at root path '/'", async () => {
    renderWithRouter("/");
    await waitFor(() => {
      expect(screen.getByText(/Operations Command Center/i)).toBeDefined();
    });
  });

  it("renders OfficePage at path '/office'", async () => {
    renderWithRouter("/office");
    await waitFor(() => {
      expect(screen.getByText(/2D Virtual Office Simulation/i)).toBeDefined();
    });
  });

  it("renders EngagementsPage at path '/engagements'", async () => {
    renderWithRouter("/engagements");
    await waitFor(() => {
      expect(screen.getByText(/Engagements & Rules of Engagement \(ROE\)/i)).toBeDefined();
    });
  });

  it("renders ReportsPage at path '/reports'", async () => {
    renderWithRouter("/reports");
    await waitFor(() => {
      expect(screen.getByText(/Security Reports & Deliverables/i)).toBeDefined();
    });
  });

  it("renders SettingsPage at path '/settings'", async () => {
    renderWithRouter("/settings");
    await waitFor(() => {
      expect(screen.getByText(/System & Simulator Configuration/i)).toBeDefined();
    });
  });

  it("renders NotFoundPage at unknown route '/unknown-route'", async () => {
    renderWithRouter("/unknown-route");
    await waitFor(() => {
      expect(screen.getByText(/404 - Page Not Found/i)).toBeDefined();
    });
  });
});
