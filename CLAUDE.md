<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Mixar

**Mixar is a custom fork of Blender 5.0 that turns Blender into an AI-powered 3D content creation tool**, with deep integrations for texture painting, AI-assisted modeling, and real-time agent chat. It's built as an **overlay system** — Mixar's source code gets layered on top of upstream Blender during build.

## Build & Development

### Build Commands
```bash
make init          # Initialize: git submodules + LFS files
make build         # Full build: overlay + CMake + compile + install packages
make clean_build   # Clean build: removes source/ and rebuilds
make install       # Install Python packages into embedded Blender Python
```

### How the Build Works
- `scripts/unix/build.sh` orchestrates the build
- `scripts/unix/overlay.sh` copies `/src` onto `/source` (Blender upstream)
- Config loaded from `.env` → env vars via `scripts/unix/settings.sh` → `scripts/generate_config.py` generates runtime `mixar.json` into the app bundle
- C++ env header auto-generated at `source/creator/mixar_env_config.h`
- Python build-frozen env marker auto-generated at `source/scripts/mixar/config/_build_env.py` (gates `get_dev_bypass_credentials`; `DEV_BYPASS_ALLOWED=True` only when `MIXAR_ENV=Dev`). Setting `DEV_BYPASS_*` env vars with `MIXAR_ENV != Dev` aborts the build.
- Python packages installed from `scripts/python_requirements.txt` into embedded Blender Python
- **Never run `cmake` or `make` directly in `source/`** — always use `make build` or `./scripts/unix/build.sh` (overlay must run first)

### Testing
```bash
pytest              # Run tests (root conftest.py stubs bpy via MagicMock)
```
Tests can run outside Blender. The root `conftest.py` injects `bpy` stubs into `sys.modules`.

## Code Rules

- Keep the code as modular, readable and performance efficient as possible. No file should be larger than 500 lines of code. Leverage C++ wherever needed to get maximum performance.
- All code goes in `/src` — it gets overlaid onto Blender source during build.
- Write all python code inside `/src/scripts/mixar/modules` in the relevant module. When in doubt, ask for the correct module.
- Place all code which can be used across modules in the `common` folder.
- All C/C++ files should be inside `src/source/blender`.
- Put all environment variables in `.env` (copy `.env.example` as template). Never commit `.env`. Config is generated at build time by `scripts/generate_config.py`.
- Keep properties and operators segregated in different folders.
- Keep all the constants for a module inside a `constants.py` file inside the module root.
- **Always update this CLAUDE.md** when features are added, modified, or deleted — keep module descriptions, architecture tables, and patterns in sync with the actual codebase.

## Bootstrap & Registration

The bootstrap system in `src/scripts/startup/bootstrap/__init__.py` handles module loading in 3 phases:

1. **Package setup** — creates synthetic packages for `/src/scripts/mixar/` (no `__init__.py` needed in subdirs)
2. **Bootstrap modules** — loads `src/scripts/mixar/bootstrap/*.py` (must have `register()`/`unregister()`)
3. **UI modules** — auto-discovers all files in `modules/**/ui/` dirs, loads in time-budgeted batches

**Key rules:**
- Only make `register` and `unregister` functions when needed. Let the fallback mechanism handle registrations — pass the list of classes properly via `classes` tuple.
- UI classes in `ui/` are auto-registered by bootstrap. Properties load first (priority 0), then operators/core (1), then panels/menus/headers (2).
- For cross-directory property dependencies, use the module's `__init__.py` to import in order (see `paint/__init__.py`).

## Project Structure

```
.env.example                       # Environment config template (copy to .env for local dev)
scripts/generate_config.py         # Generates runtime mixar.json at build time from env vars
src/
├── scripts/
│   └── mixar/
│       ├── bootstrap/         # Startup modules (agent_connection, paint_module, etc.)
│       ├── config/            # Logging config
│       └── modules/
│           ├── common/utils   # Shared utilities
│           └── {module_name}/
│               ├── constants.py  # Module constants
│               ├── core/         # Functional and calculation logic
│               └── ui/           # UI elements (auto-discovered)
│                   ├── properties/   # PropertyGroup definitions
│                   ├── operators/    # Operator definitions
│                   ├── panels/      # Panel drawing code
│                   ├── menus/       # Menu definitions
│                   └── lists/       # UIList definitions
└── source/
    └── blender/               # C/C++ extensions
```

### Active Modules
`agent_bubble`, `asset_search`, `auth`, `common`, `hunyuan`, `mesh_segment`, `moodboard`, `operation_history`, `paint`, `space_mixie`, `space_mixie_chat`, `space_texture_sets`, `texel_density`, `uv_editor`, `workflow`, `scene_grid`

---

## Core Architecture

| Layer | Location | Language | Purpose |
|-------|----------|----------|---------|
| **Blender C++ modifications** | `src/source/blender/` | C/C++ | Native editor spaces, auth, chat UI rendering |
| **Python addon** | `src/scripts/mixar/` | Python | All feature modules, UI panels, operators |
| **Backend (separate repo)** | `mixar-backend/` | Python/FastAPI | AI agent, API services, GPU job queues |
| **Upstream Blender** | `upstream/` | Git submodule | Base Blender 5.0 source |

**Build flow**: `upstream/` → copy to `source/` → overlay `src/` on top → CMake build with CUDA/OptiX → custom Blender binary.

---

## 14 Feature Modules

| Module | What it does |
|--------|-------------|
| **paint** (largest, 59MB) | Layer-based texture painting system with node trees, modifiers, baking, procedural materials, decals, UDIM, vertex colors, asset export |
| **space_mixie_chat** | AI agent chat interface — JSON-RPC 2.0 over WebSocket, SSE streaming, supervised headless sandbox script execution with Windows-safe parent liveness checks, markdown rendering |
| **agent_bubble** | Floating draggable / resizable agent chat bubble overlaid on the 3D viewport. Status pill + composer + expandable history. Bridges to space_mixie_chat backend (ConnectionManager + scene message store) so the agent integration is shared. Pure Python: GPU draw handler + persistent modal operator. |
| **moodboard** | Reference image boards, scene reconstruction, image-to-3D, 360° lookdev, scene generation. Scene Gen Experimental source remains in the tree but its operators, UIList, tab PropertyGroups, scene flags, and queue mirrors are intentionally not registered/exposed. |
| **hunyuan** | AI 3D generation (text/image → 3D mesh), retopology, UV unwrapping. Retopology offers two engines via the Topology "Model" dropdown: **Hunyuan** (backend service `retopology`) and **Tripo** (v2.0 `mesh/decimate`, backend service `retopology_tripo`). Both share the same client Retopology queue (`FEATURE_RETOPOLOGY`); the engine is chosen by the queue `job_type`/`model` sent to the backend, decoupled from the client `feature_key`. |
| **common** | Shared API clients (12 services), WebSocket infrastructure, notifications, versioning, updates |
| **auth** | OAuth PKCE flow with native keyring storage (macOS Keychain, Windows Credential Manager) |
| **asset_search** | Neural embedding-based asset library search and training |
| **mesh_segment** | UV mesh segmentation via SAM-based API |
| **texel_density** | UV texel density analysis and visualization |
| **uv_editor** | Advanced UV editing workspace with dual-space architecture, mutually exclusive tool/header panels, annotate and UV tool sidebars, dynamic panel ordering, and toolbar auto-expand |
| **space_texture_sets** | Texture set management |
| **scene_grid** | "Scene Grid" editor (`SPACE_SCENE_GRID`, C++ in `src/source/blender/editors/space_scene_grid/`): live offscreen-rendered viewport tiles of ALL scenes in an auto grid, for monitoring parallel agents (one per scene). Realtime via a 0.1s TIMERNOTIFIER poll + depsgraph change detection (`DEG_get_update_count`), so tiles follow script edits to non-active scenes with no notifiers needed. Per-tile orbit/pan/zoom, click-to-activate scene, per-scene agent busy badge (reads `mixie_chat_is_busy`). Python side: header (shading toggle) only. |
| **operation_history** | Per-session local log (`operations.jsonl` + `scripts/`) of every agent script execution plus curated manual user ops. Agent executions captured at `space_mixie_chat/core/main_thread_executor.py`; manual ops via a depsgraph→timer capture service. Read by the agent through `operation_history/core/tools.py:run_tool`. No backend DB. |
| **testing** | Pure-Python unit tests (pytest, run from repo root with bpy stubbed via root `conftest.py`) |

---

## Unified Job Queue

All AI generation features (image gen, 3D gen, retopology, UV, lookdev, brush gen, scene gen) submit through **one unified async job queue** instead of bespoke per-feature services. Lives in `modules/common/job_queue/`.

**Backend contract**: `POST /job-queue/jobs` (job_type, model, payload) → `GET /job-queue/jobs/{id}` polling → `DONE`/`FAILED`. The client `JobQueueService` wraps these.

**Client architecture**:
- **`core/job.py`** — base `Job` with shared `_unwrap_response()`, `_parse_standard_submit()`, `_parse_standard_poll()`, default `poll()`.
- **`core/generic_jobs.py`** — two generic Job classes cover all standard features:
  - `AsyncGLBJob` — submit → poll → download GLB → import (3D gen, retopology, UV, part, rapid, image-to-3D, scene gen HP/LP). Optional `on_imported` hook for rename/chain-id stamping.
  - `SyncImageJob` — submit with inline result → download images to moodboard (image gen, lookdev/depth-to-image, brush gen).
- **`core/enqueue.py`** — single `enqueue_generation(kind="glb"|"image", ...)` entry point. Builds the right Job, auto-attaches the queue listener (custom or from `scene_flag`), submits.
- **`core/helpers.py`** — `get_queue_with_listener()`, `create_scene_flag_listener()` (with `on_start`/`on_finish` hooks), `show_batch_summary_popup()`, `extract_image_urls()`, `download_images_to_moodboard()`.
- **`core/queue_manager.py`** — `FeatureQueue` drives Job lifecycle: PENDING → RUNNING_SUBMIT → RUNNING_POLL → RUNNING_DOWNLOAD → SUCCESS/FAILED.

**Per-feature enqueue helpers** (build payloads + fan-out, then call `enqueue_generation()`): `moodboard/core/generation_enqueue.py` (Pro, scene gen HP/LP), `hunyuan/core/{retopology,uv,part}_enqueue.py`. Operators call these or `enqueue_generation()` directly — **do not** create new Job subclasses for standard features. `retopology_enqueue.py` branches on the Topology `model` prop: Hunyuan → `service=retopology, model=hunyuan_topology`; Tripo → `service=retopology_tripo, model=tripo_v2` with a `tripo_params` payload (`face_limit`/`quad`/`bake`), a 150 MB export cap, and an import hook that renames to `*_low` and only Smart-UV-unwraps when `bake=false`.

**Genuinely unique jobs keep their own queue files** (custom polling/result handling): `lookdev360_queue.py` (PBR textures → fill layers), `scene_recon_queue.py` (progressive 2-phase), `scene_gen_exp_labels_queue.py` (label extraction), `mesh_segment_queue.py` (inline JSON → vertex groups), `matgen_queue.py` (inline script → procedural material).

---

## AI Agent System

The backend runs a **LangGraph-based orchestrator agent** (Claude Sonnet 4.6 primary, Gemini 3.1 Pro fallback) with:

- **18 tool domains** and **200+ tools** covering modeling, texturing, UV, rigging, particles, scene management, layer painting
- **12+ workflow modes** (MODELING, TEXTURING, RIGGING, UV_UNWRAP, SCENE, LAYER_PAINTING, etc.) that filter which tools the LLM sees
- **Tool execution pattern**: LLM calls tool → backend validates → sends Blender script via WebSocket → script uses `__PARAMS__` for input and emits `__RESULT__` JSON → result fed back to LLM

---

## C++ Customizations (~150 files)

- **26 C++ files** for native chat UI rendering (markdown, thinking visualization, hit testing, thumbnails)
- **Authentication**: Cross-platform keyring + local OAuth PKCE callback server
- **Custom editor spaces**: `space_mixie_chat`, `space_mixar_properties`, `space_mixar_layers`, `space_mixar_assets`
- **3D viewport enhancements**: 13 modified files

---

## Bootstrap & Loading

A sophisticated **two-phase registration system**:
1. **Synchronous bootstrap** (6 modules): paint property chains, agent connection, splash, caches, update checker
2. **Deferred UI loading**: ~415 Python files loaded in **4ms/frame time-budgeted batches** to keep Blender responsive during startup, with dependency-ordered priority (properties → operators → panels)

---

## Key Patterns

- **Overlay mechanism**: Mixar code overlays upstream Blender, making version upgrades cleaner
- **Singleton + daemon threads**: ConnectionManager for persistent WebSocket
- **Handler pattern**: Depsgraph handlers set flags → timers do work (avoids blocking draw)
- **Script communication**: `__PARAMS__` in, `print("__RESULT__" + json.dumps(...))` out
- **Headless sandbox supervision**: Parent Mixar process spawns a background sandbox child with platform-specific process flags; Windows children use Win32 process APIs for parent liveness checks.
- **Time-budgeted loading**: UI modules load without blocking the main loop

---

## Summary

This is a **production-grade, AI-augmented 3D creation platform** built on top of Blender. The texture painting system is the core feature (layer-based, node-driven, with procedural materials and baking), but it's surrounded by a rich ecosystem of AI capabilities — an autonomous chat agent that can manipulate the 3D scene, AI-powered 3D generation, reference moodboards, smart asset search, and mesh segmentation. The codebase is modular (~1,000+ Python files, ~150 C++ files) with clear separation between Blender-side UI/logic and backend AI services.
