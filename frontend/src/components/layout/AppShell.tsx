import React, { Suspense } from "react";
import { Outlet } from "react-router-dom";
import { AppHeader } from "../AppHeader";
import { AppNavigation } from "./AppNavigation";
import { RefreshCw } from "lucide-react";

export const AppShell: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col bg-background text-gray-100 selection:bg-primary/30 selection:text-white">
      {/* Top Application Header */}
      <AppHeader />

      {/* Main Tab Navigation Bar */}
      <AppNavigation />

      {/* Primary Content Viewport with Suspense Fallback */}
      <main className="flex-1 p-6 max-w-7xl w-full mx-auto">
        <Suspense
          fallback={
            <div className="py-24 flex flex-col items-center justify-center text-gray-400 gap-3">
              <RefreshCw className="w-6 h-6 text-primary animate-spin" />
              <span className="text-xs font-mono">Loading simulator view...</span>
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
};
