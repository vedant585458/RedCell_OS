# RedCell_OS Frontend

Interactive 2D virtual office simulation and penetration testing command center built with **React 18**, **TypeScript**, **Vite**, **Zustand**, and **PixiJS (WebGL)**.

## Architecture
- **2D Office Simulation:** Rendered using GPU-accelerated PixiJS viewport to visualize agents working at desks, holding briefings, and transitioning states at steady 60 FPS.
- **Single Source of Truth:** Purely projects backend WebSocket events without inventing independent state.
- **State Layers:**
  - `Zustand`: Event-projected agent/task entities & UI drawer controls.
  - `TanStack Query`: REST API mutations and report fetches.

## Directory Structure
- `src/`
  - `components/`: Command center, approvals, logs, reports, task DAG inspectors.
  - `office-world/`: PixiJS 2D canvas, viewport, sprite animations, room tilesets.
  - `state/`: Zustand stores and WebSocket client listener.
  - `api/`: REST query client.
