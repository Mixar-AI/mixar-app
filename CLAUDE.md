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
- **Git worktrees build out of the box**: `upstream/` is a multi-GB submodule that linked worktrees don't carry, so `settings.sh` falls back to the main checkout's `upstream/` (read-only rsync source; warns if the shared tree isn't at the commit the branch pins). Override with `MIXAR_UPSTREAM_DIR`. Each worktree still assembles its own `source/` and `build/` — never share those.
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
`agent_bubble`, `agent_scene_strip`, `agent_viewport_lock`, `asset_search`, `auth`, `common`, `hunyuan`, `mesh_segment`, `moodboard`, `onboarding`, `operation_history`, `paint`, `space_mixie`, `space_mixie_chat`, `space_texture_sets`, `texel_density`, `uv_editor`, `workflow`

**onboarding** — first-run feature tour: GPU-rendered cards (`core/card/`), dim film + green highlight border (`core/overlay/`). The three sidebar-step highlights (Image Gen / Model Gen / Retopology) measure the rendered panel extent dynamically via `region.view2d.tot_rect` — a Mixar RNA addition in `rna_screen.cc` exposing the View2D total rect — because catalog-driven tab heights vary per mode/model; the `SIDEBAR_PANEL_H_*` constants are only a fallback for builds without that overlay. Top-left cards (welcome/completion) reserve vertical clearance above the floating Agent Bubble window (`host_resolver.bubble_clearance_height`) so the card scales down instead of being cropped behind the bubble.

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

## Feature Modules

| Module | What it does |
|--------|-------------|
| **paint** (largest, 59MB) | Layer-based texture painting system with node trees, modifiers, baking, procedural materials, decals, UDIM, vertex colors, asset export |
| **space_mixie_chat** | AI agent chat interface — JSON-RPC 2.0 over WebSocket, SSE streaming, supervised headless sandbox script execution with Windows-safe parent liveness checks, markdown rendering, and post-response 1–5-star feedback with optional comments. **Reconnect-resume**: the WS client has a recv-liveness watchdog (`WS_LIVENESS_TIMEOUT` — a silently dead TCP connection never errors on send, only recv starvation reveals it) that tears down + auto-reconnects; active-turn scene states deliberately survive WS loss (`on_disconnected` only offlines IDLE/CONNECTING) so resumed tool calls aren't rejected, and the status pill/chat header derive "Reconnecting" from transport liveness instead of scene state. **Transport liveness is a separate, faster signal than `is_connected`**: `is_transport_live` trips on `WS_UI_STALE_THRESHOLD` (~20s) of recv silence, so the UI stops claiming Connected within seconds of a network drop instead of waiting out the 45s teardown watchdog (`is_connected` stays True on a zombie socket until then — send-gating must keep using it, a false "down" there drops work); a 2s main-thread liveness-monitor timer (`ConnectionManager._start_liveness_monitor`) repaints the pill/header on liveness flips, since a silent death produces no scene-state edge to redraw on. A mid-turn SSE loss (fast-detected: backend sends ~15s keepalives, client read timeout 75s) re-attaches via `POST /agent/chat/attach`, which replays the backend's seq-stamped Redis event buffer and follows live until [DONE]; the client dedups the replayed overlap by `seq` (`_last_seq` spans the chat + input streams of one turn, reset on a new chat POST). Never re-POST a lost accepted stream — that starts a duplicate turn. |
| **agent_viewport_lock** | "Agent is working" viewport treatment: a breathing green inner-glow halo (SpaceView3D POST_PIXEL draw handler) plus an input-block modal that consumes selection/edit input over the 3D viewport while passing camera navigation. Active while an AGENT-mode turn is executing (BUSY/MODIFYING). Gated on `scene.mixie_chat_active_turn_mode` — the mode the *running* turn was started in, stamped/cleared by `SessionManager.set_state` on active-state edges — not the live `mixie_chat_mode` dropdown, so flipping Agent→Ask→Agent mid-turn can't drop the lock (or raise it for a running Ask turn). |
| **agent_bubble** | Floating draggable / resizable agent chat bubble overlaid on the 3D viewport. Status pill + composer + expandable history, including the shared post-response rating/comment controls. Bridges to space_mixie_chat backend (ConnectionManager + scene message store) so the agent integration is shared. Pure Python: GPU draw handler + persistent modal operator. **Lifecycle invariants (crash-class fixes)**: bubble/pill wmWindows are NEVER serialized — every WM-layer `BLO_write_file` caller (interactive save, save-startup, AND `WM_autosave_write`) unlinks them via `wm_agent_bubble_windows_unlink_for_write`; files that already carry them (old autosaves) are stripped on read by `wm_file_read_strip_agent_bubble_windows` (wm_files.cc, runs in `wm_file_read_setup_wm_finalize` before the first `WM_check`, GUI only) and excluded from ghost-window winid matching. The cached raw GHOST pointers (`g_bubble_ghostwin`/`g_pill_ghostwin`/`g_host_ghostwin`) are invalidated at BOTH chokepoints: `wm_window_close` (space-based, `ED_agent_bubble_windows_closed`) and `wm_window_free` (pointer-based, `ED_agent_bubble_window_freed` — covers file-load WM replacement that bypasses close). Natively-hidden windows (minimised bubble `SW_HIDE`/`orderOut:`, modal-suppressed docks) are skipped in `wm_draw_update` via `Mixar_WindowIsVisible` (GHOST Win32+Cocoa) — presenting GL into a hidden window is what crashed NVIDIA's driver (`DrvPresentBuffers`) after resume-from-sleep; restore paths must tag a redraw after re-showing (they do — `bubble_force_size_and_refresh` / `NC_WINDOW` notifier in `wm_mixar_floating_docks_restore_after_modal`). Header right side: new-chat button (only when history exists) plus an icon-only reconnect button (reuses `mixie_chat.connect`) shown only when logged in and the session is OFFLINE; the status pill shows "Reconnecting" whenever the WS transport is down while scene state is non-offline (down = `is_transport_live` False, i.e. recv-stale past ~20s — not the slower `is_connected`). |
| **moodboard** | Reference image boards with lossless in-app and cross-platform system clipboard copy/paste, scene reconstruction, image-to-3D, 360° lookdev, scene generation. Scene Gen Experimental source remains in the tree but its operators, UIList, tab PropertyGroups, scene flags, and queue mirrors are intentionally not registered/exposed. The **Image Gen tab** is catalog-driven: model/style dropdowns source `generation_catalog_cache`, settings past style/model render via `generation_params.draw_service_params()`, and the generate operator builds `payload["params"]` from `collect_params("image_gen", model)` — hardcoded enums remain as the offline/pre-auth fallback. The tab also carries a Mode dropdown for the `image_gen` capability's services (paint-surfaced `brush_gen` is filtered out). **From Blockout (`depth_to_image`) lives under whichever capability the catalog assigns it** — the dedicated **AI Render** tab (capability `ai_render`, `ui/ai_render_drawer.py`) or the Image Gen tab's From Blockout mode — and moving it between them is a DB-only `capability_id` flip: the drawing logic is the SHARED `ui/blockout_drawer.py` (never fold it into one tab's drawer), both host tabs carry a catalog model enum, and `lookdev_scene_ops` reads the model from whichever tab currently hosts the service. It renders the Blockout-to-Render inputs (`tab_lookdev` prompt + fast_mode) plus the catalog Model dropdown/schema params and submits through the EXISTING depth-capture flow (`mixie.lookdev_generate` → `lookdev_generate_from_scene`, payload shape unchanged, model slug + params catalog-resolved with `flux-depth-dev`/`{}` fallback). The **Model Gen tab** (panel `MIXIE_PT_gen_image_to_3d`, bl_category "Model Gen") consolidates the catalog's `model_gen` capability: a Mode dropdown (Image to 3D / Image to 3D Pro / Rapid 3D = services `model_3d`/`image_to_3d`/`hunyuan_rapid`), per-mode Model dropdown + schema params via `draw_capability_selector()`, shared input-image UI, Pro-only multi-view pickers (reusing `scene.hunyuan.pro` state/operators), and `mixie.model_gen_generate` (`ui/operators/model_gen_ops.py`) which routes by mode through the payload assemblers onto each mode's existing feature queue/scene flag/import hook. Catalog-not-loaded falls back to the legacy Basic/Pro subtab UI (`sidebar_panel_drawers._draw_image_to_3d`); the drawer lives in `ui/model_gen_drawer.py`. **Stage 2b converted the remaining tabs**: **Texture Gen** (panel `MIXIE_PT_gen_lookdev360`, bl_category "Texture Gen") — capability `texture_gen`, modes PBR Textures/`pbr_gen` (existing `mixie.lookdev360_generate` pipeline, resolution now schema-driven), Texture Edit/`hunyuan_texture_edit` (`mixie.texture_edit_generate` in `ui/operators/texture_gen_ops.py`: FBX export + reference image XOR prompt, shares `FEATURE_LOOKDEV360`), and Procedural Material/`mat_gen` (`mixie.texture_gen_matgen` → paint-side `enqueue_matgen_job`, catalog slug fast/detailed = pipeline); drawer `ui/texture_gen_drawer.py`. **Retopology** — capability `retopology`, drawer `ui/retopology_drawer.py` + `mixie.retopology_generate` (`ui/operators/retopology_gen_ops.py`) fanning out through `enqueue_retopology_jobs`; Tripo "Bake Textures" stays client-side on `scene.hunyuan.topology.tripo_bake`. **UV Unwrap** — capability `uv_unwrapping` (single service, Mode hidden): the catalog Model dropdown/params append to the existing drawer, submit flow unchanged. **Mesh Segment** — capability `mesh_segmentation` with modes `mesh_segment` (existing flow) and `hunyuan_part` (embeds the former PART_SEGMENT flow). **Scene Recon** — pipeline flags schema-driven from service `scene_reconstruction` (`_gather_recon_params` in `scene_recon_ops.py`); `save_to_library`/`asset_library_path` remain plain Blender props. Catalog Mode/Model enum selections for tabs without their own prop group live in `ui/moodboard_catalog_tab_props.py` (registered via `moodboard_scene_registration.py` before the sidebar container). Every tab keeps its legacy hardcoded UI as the catalog-not-loaded fallback. **Stage 3 — final sidebar** (`ui/moodboard_sidebar_panels.py`): exactly one N-panel per catalog capability, in catalog sort order — Image Gen, AI Render, Model Gen, Texture Gen, Scene Gen, Retopology, UV Unwrapping, Mesh Segmentation — plus the Queue utility panel (`mixie.queue_view` keys on its category). AI Render is catalog-only: unlike the seven legacy tabs it has no offline fallback, so its `poll()` requires a loaded catalog with `ai_render` services (empty/absent capability = hidden tab, which makes the depth_to_image move revertible from the DB alone). **Scene Gen** (panel `MIXIE_PT_gen_scene_recon`, `ui/scene_gen_drawer.py`) merges Scene Reconstruction (`scene_reconstruction`) and Segments to 3D (`scene_gen`) behind a Mode dropdown; each mode's operator/payload flow is untouched. Panels are STATIC (labels mirror the DB capability labels — runtime re-registration for relabelling is fragile) with catalog-driven content, and each panel's `poll()` hides the tab when the loaded catalog has no moodboard services for its capability; offline all 7 tabs render legacy fallbacks. Removed in Stage 3: the Blockout panel (absorbed into Image Gen), the Segment panel (merged into Scene Gen), the legacy single-panel tab strip (`moodboard_sidebar_panel.py`) + `core/sidebar_animation.py`, the sidebar `active_tab`/`imagegen_subtab`/`segmentation_subtab` enums (`image_to_3d_subtab` survives for the Model Gen offline fallback), and the dead hunyuan/part/rapid drawers in `sidebar_tab_drawers.py`. Segmentation tools (magic select, box/lasso mask) surface results via `sidebar_ui_helpers.focus_scene_gen_segments()`. **Auto Rig** (panel `MIXIE_PT_gen_animate`, bl_category "Auto Rig", `ui/animate_drawer.py` + `mixie.animate_generate` in `ui/operators/animate_gen_ops.py`) — catalog-only like AI Render (poll requires loaded catalog with `animate` services, no offline fallback): capability `animate`, single service `tripo_rig` (per-selected-mesh GLB export ≤150MB through `hunyuan/core/animate_enqueue.py`), on the client `FEATURE_ANIMATE` queue. Rigged glTF is imported with `guess_original_bind_pose=False` (`import_options` threaded through `enqueue_generation`) so Tripo rigs don't collapse. The Tripo retarget/animation mode is not seeded in the catalog (the backend seed `animate_catalog.sql` is Auto-Rig-only); the backend `tripo_retarget` adapter code remains but is unreachable. Agent-accessible: the backend `GENERATION_SPECS['tripo_rig']` (job_type `tripo_rig`) dispatches the client `mixie.agent_auto_rig` operator (`ui/operators/agent_auto_rig_ops.py`) with an explicit `object_name` — the RiggingAgent lane (`lanes/rigging`) is prompted to ALWAYS auto-rig via this tool and never hand-build armatures with scripts unless the user explicitly asks for manual rigging. All generate operator bl_idnames and `scene.hunyuan.*` property groups are unchanged (frozen agent contracts). |
| **hunyuan** | AI 3D generation (text/image → 3D mesh), retopology, UV unwrapping. Retopology offers two engines as **models of the one `retopology` backend service**: **Hunyuan** (`hunyuan_topology`) and **Tripo** (`tripo_v2`, v2.0 `mesh/decimate`); pre-merge catalogs still expose Tripo as the separate `retopology_tripo` service and the enqueue follows whichever service the catalog resolved. Both share the same client Retopology queue (`FEATURE_RETOPOLOGY`); the engine is chosen by the queue `job_type`/`model` sent to the backend, decoupled from the client `feature_key`. Also hosts the Auto Rig enqueue helpers (`core/animate_enqueue.py`): Tripo v3 auto-rig (`tripo_rig`) jobs for the moodboard Auto Rig tab (the retarget/animation path was removed from the catalog; dormant backend code remains). |
| **common** | Shared API clients (13 services), WebSocket infrastructure, notifications (server notifications with `action_url` + optional `action_label` render a primary link button — `NotificationAction.url` carries the URL through the toast click dispatch, opens via `wm.url_open`, and sends the read receipt; built in `store.push_from_server`), versioning, auto-updates (**browser-based only** — the update toast's [Download] opens the downloads page; there is NO in-app download/installer launch, that machinery was removed after MSI launch failures on Windows. Startup check, forced-update enforcement, Help → Check for Updates, and a persistent topbar "Update Available" badge right of Open Mixie — `updates/ui/topbar_badge.py`, drawn from agent_bubble's topbar hook; clicking re-shows the sticky update toast, badge persists after Skip/dismiss, and redraws are forced via the Mixar `Window.global_areas` RNA since the topbar is a global area), and `generation_params/` — the schema-driven parameter engine (see Generation Catalog section) |
| **auth** | OAuth PKCE flow with native keyring storage (macOS Keychain, Windows Credential Manager) |
| **asset_search** | Neural embedding-based asset library search and training |
| **mesh_segment** | UV mesh segmentation via SAM-based API |
| **texel_density** | UV texel density analysis and visualization |
| **uv_editor** | Advanced UV editing workspace with dual-space architecture, mutually exclusive tool/header panels, annotate and UV tool sidebars, dynamic panel ordering, and toolbar auto-expand |
| **space_texture_sets** | Texture set management |
| **Agent Scene Strip** (C++ region + `agent_scene_strip` Python keymap module) | Bottom-docked View3D region (`RGN_TYPE_EXECUTE`, `src/source/blender/editors/space_view3d/view3d_agent_strip*`): live offscreen-rendered viewport tiles of **every scene except the window's active one**, for monitoring parallel agents (one per scene) without leaving the viewport. Replaces the removed Scene Grid editor space (`SPACE_SCENE_GRID` = 109, enum value reserved). Poll-driven region: auto-shows when the file has more than one scene, auto-hides otherwise. Realtime via a 0.1s TIMERNOTIFIER poll + depsgraph change detection (`DEG_get_update_count`), so tiles follow script edits to non-active scenes with no notifiers needed. Per-tile orbit/pan/zoom (`VIEW3D_OT_agent_strip_*`), click-to-activate scene (swaps that tile out for the previous active scene), per-scene `mixie_chat_is_busy` badge; tiles follow the host viewport shading (solid/material). Mixar file subversion 100.3 adds the region to previously saved View3D areas. Key bindings live in `modules/agent_scene_strip/ui/keymap.py` (addon keyconfig): the GUI keyconfig preset reload wipes items from all C-registered keymaps in the default config, so C-side `WM_keymap_add_item` bindings go dead in GUI sessions — addon-keyconfig registration is the required pattern for custom C region keymaps (same as `space_mixie_chat`). |
| **operation_history** | Per-session local log (`operations.jsonl` + `scripts/`) of every agent script execution plus curated manual user ops. Agent executions captured at `space_mixie_chat/core/main_thread_executor.py`; manual ops via a depsgraph→timer capture service. Read by the agent through `operation_history/core/tools.py:run_tool`. No backend DB. |
| **testing** | Pure-Python unit tests (pytest, run from repo root with bpy stubbed via root `conftest.py`) |

---

## Unified Job Queue

All AI generation features (image gen, 3D gen, retopology, UV, lookdev, brush gen, scene gen) submit through **one unified async job queue** instead of bespoke per-feature services. Lives in `modules/common/job_queue/`.

**Backend contract**: `POST /job-queue/jobs` (job_type, model, payload) returns the submit acknowledgement, then the shared agent WebSocket drives state via compact `job.update` pushes and full `job.get` / `job.sync` reconciliation (the watchdog requests sync; it does not run a recurring REST poll). Client views include the submitted `model`; missing model fields from older backends must not erase the locally submitted value.

**Client architecture**:
- **`core/job.py`** — base `Job` with shared model display metadata, optional catalog-backed `origin_capability_key` for composite workflows, missing-safe backend metadata merging, `_unwrap_response()`, `_parse_standard_submit()`, `_parse_standard_poll()`, and default `poll()`.
- **`core/generic_jobs.py`** — two generic Job classes cover all standard features:
  - `AsyncGLBJob` — submit → poll → download GLB → import (3D gen, retopology, UV, part, rapid, image-to-3D, scene gen HP/LP). Optional `on_imported` hook for rename/chain-id stamping.
  - `SyncImageJob` — submit with inline result → download images to moodboard (image gen, lookdev/depth-to-image, brush gen).
- **`core/enqueue.py`** — single `enqueue_generation(kind="glb"|"image", ...)` entry point. Builds the right Job, auto-attaches the queue listener (custom or from `scene_flag`), submits.
- **`core/helpers.py`** — `get_queue_with_listener()`, `create_scene_flag_listener()` (with `on_start`/`on_finish` hooks), `show_batch_summary_popup()`, `extract_image_urls()`, `download_images_to_moodboard()`.
- **`core/queue_manager.py`** — `FeatureQueue` drives Job lifecycle: PENDING → RUNNING_SUBMIT → RUNNING_POLL → RUNNING_DOWNLOAD → SUCCESS/FAILED. The unified queue row joins backend `service`/`model` keys to generation-catalog capability and model labels. Exact raw identifiers are used only when the catalog is unavailable or no longer contains a historical row. Composite workflows such as Scene Gen HP/LP carry `origin_capability_key=scene_gen`, so the badge follows the backend's current Scene Gen label even though the submitted execution service belongs to another capability. Jobs whose stable `label` also carries dedup/downstream naming data provide a separate `display_label`; never parse prompt/object text to remove prefixes. Do not add client-side generation naming maps.

**Per-feature enqueue helpers** (build payloads + fan-out, then call `enqueue_generation()`): `moodboard/core/generation_enqueue.py` (Pro, scene gen HP/LP), `hunyuan/core/{retopology,uv,part}_enqueue.py`. Operators call these or `enqueue_generation()` directly — **do not** create new Job subclasses for standard features. `retopology_enqueue.py` branches on the shared snapshot's `model` key (`hunyuan`/`tripo`, set by the legacy Topology prop or the catalog tab): Hunyuan → `service=retopology, model=hunyuan_topology`, `params` `polygon_type`/`face_level`/`post_process`; Tripo → `model=tripo_v2`, `params` `quad`/`face_limit`/`bake` (backend clamps face_limit), a 150 MB export cap, and an import hook that renames to `*_low` and only Smart-UV-unwraps when `bake=false`. Tripo submits to `shared["service_key"]` — the merged `retopology` service on current catalogs, falling back to the legacy `retopology_tripo` service (pre-merge catalogs / legacy props path). `shared["model_slug"]` overrides the model constants when the catalog tab selects one.

**Genuinely unique jobs keep their own queue files** (custom polling/result handling): `lookdev360_queue.py` (PBR textures → fill layers), `scene_recon_queue.py` (progressive 2-phase), `scene_gen_exp_labels_queue.py` (label extraction), `mesh_segment_queue.py` (inline JSON → vertex groups), `matgen_queue.py` (inline script → procedural material).

---

## Generation Catalog & Dynamic Params

Foundation for the DB-driven moodboard tabs — the sidebar is exactly the 7 capability tabs (Image Gen, Model Gen, Texture Gen, Scene Gen, Retopology, UV Unwrapping, Mesh Segmentation) plus Queue, each with a legacy offline fallback.

- **`bootstrap/generation_catalog_cache.py`** — owns lock-guarded lifecycle and ETag revalidation for `GET /api/v1/generation-catalog` (capabilities → services → models → parameter schemas, plus styles and credit costs). Disk I/O lives in `bootstrap/generation_catalog/storage.py`; read-only typed lookups live in `bootstrap/generation_catalog/queries.py`. Keeping these pure helpers in a subpackage leaves the lifecycle module below the 500-line limit and prevents the top-level bootstrap loader from executing them twice. The cache uses 2s-delayed background fetch, logout clear, manual refresh, and persisted stale data (`generation_catalog.json` in `bpy.utils.user_resource('DATAFILES', path='mixar')`) so panels render instantly on launch. Public accessors include `get_capabilities/get_capability/get_capability_for_service/get_services(capability, surface)/get_models/get_model/get_styles/get_credit_cost/is_loaded` plus enum-item helpers with LOADING/ERROR placeholders. Services carry `surface` (`moodboard`|`paint`) — paint-only services must never appear in moodboard tabs.
- **`modules/common/generation_params/`** — schema-driven parameter engine: dynamically builds one PropertyGroup per (service, model) from catalog schemas, attached to **WindowManager** pointers (not Scene) so re-registration on catalog change is safe (no .blend/undo persistence; rebuilds run on a main-thread timer scheduled by the cache). `draw_service_params(layout, service, model)` renders widgets by schema `widget` kind honoring `order`/`group`/`visible`/`visible_if`; `collect_params(service, model)` returns visible params as a typed plain dict for payloads. Never hardcode param names here — key sets change from the DB without client releases. Design rationale in `core/engine.py` docstring. Two more layers live here: **`core/selector.py`** — capability mode selector (`get_service_enum_items()` Mode-dropdown items with LOADING/ERROR placeholders, `resolve_service_key()` mode-enum→valid service key, `draw_capability_selector()` Mode→Model→params rendering that returns False when the catalog isn't loaded so tabs fall back to legacy UI); and **`core/assemblers.py`** — the generic wire contract: `assemble_payload(service, params, payload, model_slug)` puts `collect_params()` output (plus `prompt` where a service takes one) into `payload["params"]` (snake_case, None values dropped) for EVERY service; file/image inputs stay top-level (`image_bytes_b64`, `file_bytes_b64`, `multi_view_images`, ...). The backend provider adapters own all vendor mapping (Tencent PascalCase `sdk_params`, Tripo decimate body + face-limit clamping, fal snake_case) — never build provider shapes client-side. `resolve_model_slug()` (selector.py) maps a model enum value to a valid catalog slug with a hardcoded fallback. Bespoke-queue services (`pbr_gen`, `mesh_segment`, `scene_reconstruction`, `mat_gen`) have no assembler entry: their Jobs build payloads from dataclass fields, so catalog params thread through the enqueue helpers' kwargs instead.
- **Legacy caches retired** — `bootstrap/imagegen_cache.py` / `model_3d_cache.py` were deleted (Stage 3); every consumer (moodboard enum callbacks, space_mixie popup props, paint brush-gen models, auth login/logout hooks, refresh operators, default-model/max-refs lookups) reads the generation catalog cache, with static hardcoded lists as the last-resort offline/pre-auth fallback. `generation_params.get_param_enum_items(service, model, param)` serves legacy enum props that mirror a schema param (e.g. aspect_ratio/resolution) outside the dynamic engine.

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
- **Python GIL safety**: `python/generic/py_capi_utils.cc` overlay — `PyC_IsInterpreterActive()` uses per-thread `PyGILState_Check()` instead of the process-global current-tstate check. On Python ≤ 3.11 the global check answers "does *any* thread hold the GIL", which let C++ operators (GIL released around `WM_operator_call_py`) call Python C-API concurrently with background Python threads (auth/keyring, cache fetchers) → allocator corruption → startup segfaults in `PyUnicode_New`.

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
