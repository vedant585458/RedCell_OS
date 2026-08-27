# ADR-002: Frontend Framework, State Management Layer, and 2D Office World Renderer

**Status:** Accepted  
**Date:** August 2026  
**Milestone Reference:** M006  
**Phase:** P02 — Architecture and Technology Decisions  
**Context Link:** [VISION.md](../../VISION.md), [ADR-001-backend-runtime.md](ADR-001-backend-runtime.md)  

---

## 1. Context & Problem Statement

RedCell_OS pairs a professional security command-and-control dashboard with a real-time, interactive **2D virtual office simulation**. 

In the office view, AI employee agents (CISO, Recon Specialists, Exploit Verifiers, Report Writers) are visualized working at their desks, walking to meeting rooms for cross-department briefings, updating department kanban boards, and displaying status indicators (idle, active, blocked on approval, executing tool). Concurrently, the dashboard provides live terminal logs, DAG task graphs, approval gate prompts, and ROE configuration panels.

### The Architectural Invariant:
> **"Backend is the single source of truth; frontend renders derived state only, never invents animation state not backed by an event."**

We must choose:
1. The **Frontend UI Framework & Build Tooling**.
2. The **State Management Architecture** for bifurcating server-derived state from local UI state.
3. The **2D Rendering Engine** capable of scaling from the 3-agent MVP to enterprise simulations with hundreds of simultaneous agents without frame drops.

---

## 2. Decision Drivers

1. **High-Performance 2D Rendering:** Smooth 60 FPS rendering of 2D office environments, department zones, furniture, and animated agent sprites scaling up to 500+ active entities.
2. **Strict Event-Driven State Flow:** Frontend must ingest high-frequency WebSocket event streams without dropping frames or triggering full-page DOM re-render storms.
3. **Clean Decoupling:** The 2D graphical canvas and standard React UI elements (modals, terminals, forms) must communicate cleanly through a shared, reactive state store.
4. **Developer Ergonomics & Ecosystem:** Modern TypeScript support, fast HMR build tooling (Vite), component modularity, and lightweight bundle size.

---

## 3. Decision

We decide to adopt the following technology stack:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FRONTEND TECHNOLOGY STACK                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    Application Shell & UI Controls                    │  │
│  │  • React 18+ (TypeScript) + Vite Build Tool                           │  │
│  │  • Tailwind CSS + Lucide Icons (Command Center & Inspector Panels)    │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│  ┌───────────────────────────────────┴───────────────────────────────────┐  │
│  │                  State Management & Data Synchronization              │  │
│  │  • Zustand: Real-time event projection store & client UI state        │  │
│  │  • TanStack Query (React Query): REST API query caching & mutation    │  │
│  │  • WebSocket Client Manager: Auto-reconnecting binary/JSON stream     │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│  ┌───────────────────────────────────┴───────────────────────────────────┐  │
│  │                2D Office Simulation Render Engine                     │  │
│  │  • PixiJS (WebGL / WebGPU Hardware Acceleration)                      │  │
│  │  • Pixi Viewport (Pan, Zoom, Drag, Minimap)                           │  │
│  │  • Sprite Sheet Animations & Tweening for Agent FSM State Movement    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Evaluated Alternatives for 2D Office Rendering

We evaluated three architectural approaches for rendering the 2D office simulation:

| Feature / Criteria | Approach A: PixiJS (WebGL) [CHOSEN] | Approach B: Konva / React-Konva (Canvas 2D) | Approach C: DOM / SVG / CSS Nodes |
|---|---|---|---|
| **Underlying Technology** | WebGL 2.0 / WebGPU with 2D Canvas Fallback | HTML5 2D Canvas Context | Standard HTML `<div>` / SVG Elements |
| **Rendering Performance** | Hardware-accelerated GPU batching; $> 10,000$ sprites @ 60 FPS | CPU-bound 2D Canvas; drops frames at $> 300$ animated nodes | Severe DOM thrashing & layout reflows beyond 50 nodes |
| **Sprite & Texture Management** | Native Texture atlases, SpriteSheets, and GPU mipmapping | Basic image objects loaded into canvas | CSS background images / SVG vectors |
| **Camera & Viewport (Pan/Zoom)** | Native transform matrix; sub-millisecond smooth zoom/pan | Manual canvas matrix manipulation | Heavy CSS `transform: matrix()` with blur/aliasing |
| **Visual Effects & Shaders** | Native GLSL filters (lighting, scanlines, selection outlines) | Limited canvas filter operations | Heavy CSS filters |
| **Scalability to Enterprise** | Scales effortlessly to hundreds of concurrent agents | Bottlenecks at high agent counts | Fails completely at scale |

### Why PixiJS Won:
- **Scalability Guarantee:** A single engagement may involve dozens of active agents across multiple departments emitting high-frequency status changes. PixiJS’s WebGL batch renderer guarantees steady 60 FPS performance regardless of entity count.
- **Rich 2D Feature Set:** Built-in support for texture packing, animated sprite sheets, tinting, particle emitters (e.g. scan pulse effects), and interactive hit testing.

---

## 5. State Management Architecture

To maintain the architectural principle that **the backend is the single source of truth**, state is cleanly segmented into three distinct categories:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STATE CATEGORIZATION MATRIX                        │
├──────────────────────────┬───────────────────────┬──────────────────────────┤
│ State Category           │ Management Technology │ Purpose & Lifecycle      │
├──────────────────────────┼───────────────────────┼──────────────────────────┤
│ 1. Server Event State    │ **Zustand** (Store)   │ Projected state from     │
│    (Agents, Tasks, Logs, │                       │ WebSocket event stream.  │
│     Findings, ROE status)│                       │ Strictly append/update.  │
├──────────────────────────┼───────────────────────┼──────────────────────────┤
│ 2. Async REST Queries    │ **TanStack Query**    │ Historical engagement    │
│    (Reports, Artifacts,  │ (React Query)         │ lists, exported ZIPs,    │
│     Target Config)       │                       │ schema fetches.          │
├──────────────────────────┼───────────────────────┼──────────────────────────┤
│ 3. Ephemeral UI State    │ **Zustand** / Local   │ Selected agent drawer,   │
│    (Active Tab, Zoom,    │ `useState`            │ modal open/close, search │
│     Muted Channels)      │                       │ filters, terminal scroll.│
└──────────────────────────┴───────────────────────┴──────────────────────────┘
```

### Why Zustand + TanStack Query?
- **Zustand:** Provides an un-opinionated, ultra-fast store that supports direct updates outside of React component render cycles (crucial when WebSocket messages arrive rapidly). Components subscribe only to specific selectors (`useStore(state => state.agents[id])`), preventing unnecessary re-renders.
- **TanStack Query:** Handles caching, automatic refetching, and error states for REST endpoints without bloating the primary event store.

---

## 6. Frontend Architectural Blueprint

```
src/
├── app/
│   ├── App.tsx                     # Top-level application router and layout
│   └── main.tsx                    # React root entry point
├── components/
│   ├── command-center/             # Engagement control, Kill Switch, ROE status
│   ├── approval-gates/             # Modal & banner for HITL operator approval
│   ├── task-inspector/             # DAG visualizer and agent task timeline
│   ├── log-terminal/               # Virtualized streaming log console
│   └── report-viewer/              # Markdown & artifact previewer
├── office-world/                   # PixiJS 2D Simulation Engine
│   ├── OfficeViewport.tsx          # React wrapper for PixiJS Application
│   ├── stage/                      # Grid, Department zones, Walls, Desks
│   ├── sprites/                    # Agent sprites, State animations, Emotes
│   ├── controllers/                # Movement tweening, Pathfinding, Camera
│   └── textures/                   # Sprite atlases and room tilesets
├── state/
│   ├── eventStore.ts               # Zustand store populated via WebSocket
│   ├── uiStore.ts                  # Local UI drawer, selection, and zoom state
│   └── socketClient.ts             # Reconnecting WebSocket listener
└── api/
    └── engagementApi.ts            # TanStack Query client hooks
```

---

## 7. Consequences & Trade-offs

### Positive Consequences
- **True 60 FPS Visuals:** PixiJS offloads all sprite rendering and animations to the GPU, leaving the main JS thread free for WebSocket processing and UI logic.
- **Zero Hallucinated Animation:** Agent sprite movements and desk activities are triggered exclusively by backend FSM state transition events (`PLANNING` $\rightarrow$ walks to whiteboard, `EXECUTING` $\rightarrow$ typing at desk, `AWAITING_APPROVAL` $\rightarrow$ raising alert badge).
- **Clean Separation of Concerns:** React handles complex forms, tables, and inspection drawers while PixiJS handles the immersive 2D virtual office.

### Negative Consequences & Mitigations
- **Canvas / DOM Coordinate Synchronization:** Tooltips and overlays anchored to sprites require converting PixiJS world coordinates to DOM screen coordinates.
  - *Mitigation:* Implement a lightweight coordinate projection helper inside the `OfficeViewport` controller.
- **Dual React / Pixi Lifecycle Management:** PixiJS instances must be cleanly destroyed on unmount to prevent WebGL context leaks.
  - *Mitigation:* Encapsulate Pixi Application lifecycle within a dedicated React custom hook with strict cleanup routines.

---

## 8. Review & Acceptance

- **Accepted By:** RedCell_OS Architecture Review Board
- **Traceability:** Fulfills milestone **M006**, unlocking all frontend milestones across Phase P02 and Phase P30+ (Office Simulation).
