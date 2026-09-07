<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Mixar (Blender client)

**Mixar is a custom fork of Blender 5.2 that turns Blender into an AI-powered 3D content creation tool** — layered texture painting, AI 3D generation, and a real-time chat agent that drives the scene. This repo is the **desktop client**; the AI backend is the separate `mixar-backend` repo (FastAPI), and the admin dashboard is `mixar-admin-dashboard`.

This file holds the build model, the rules, and the module map. It is published with the source, so it references only published paths.

## Overlay Build Model (the #1 thing to understand)

All Mixar source lives in `/src` and is rsync'd **on top of** upstream Blender at build time:

```text
upstream/    Blender 5.2 source (git submodule)
src/         Mixar overlay — ALL Mixar code goes here
source/      GENERATED: upstream/ copied here, then src/ overlaid. NEVER edit directly.
build/<env>/ CMake build output (e.g. build/Prod/bin, build/Dev/bin)
```

- Python → `src/scripts/mixar/modules/{module}`; C/C++ → `src/source/blender/`.
- **Never run `cmake`/`make` inside `source/`** — always `make build` (overlay must run first).
- CMake install clears the bundled `scripts/mixar` package before recopying, so incremental builds cannot retain Python modules deleted from `/src`.
- The overlay copy (`overlay.sh` rsync / `overlay.bat` robocopy) skips git-ignored local junk inside `src/` — `.venv/`, `venv/`, `__pycache__/`, `.pytest_cache/`, `.DS_Store`. CMake's `scripts/` install rule filters only `__pycache__`, so a stray dev venv would otherwise ship in the app bundle.
- **Git worktrees build out of the box**: `settings.sh` falls back to the main checkout's `upstream/` (the multi-GB submodule doesn't carry into linked worktrees; used read-only as the rsync source, warns if not at the pinned commit). Override with `MIXAR_UPSTREAM_DIR`; each worktree still assembles its own `source/` and `build/` — never share those.
- **macOS dev codesign (optional)**: `MIXAR_DEV_SIGN_ID` in `.env` makes `build.sh` re-sign the built `Mixar` executable with a stable self-signed identity (one-time setup: `scripts/unix/setup_dev_codesign.sh`), so the Keychain "Always Allow" sticks across rebuilds. Signs with `get-task-allow` so lldb attach keeps working. Local dev only — release signing is a separate pipeline.

## Build, Run, Test

```bash
make init            # git submodules + LFS
make build           # overlay + CMake + compile + install packages (scripts/unix/build.sh)
make clean_build     # wipe source/ and rebuild
make install         # install Python packages into embedded Blender Python
make run [Prod|Dev]  # launch the built app (default build/Dev)

python -m pytest -q  # standalone suite, runs OUTSIDE Blender (root conftest.py stubs bpy)
python -m pytest -q src/scripts/mixar/modules/testing  # legacy/embedded suite (needs runtime deps)
```

- Python packages are installed from `scripts/python_requirements.txt` into the embedded Blender Python (`make install`).
- `pytest.ini` testpaths: `tests/`, plus in-tree suites under `space_mixie_chat/tests` and `paint/{layered_build,procedural_materials}/tests`. `pythonpath = src/scripts`.
- `bpy` is a MagicMock in tests, so `bpy.types.Operator` subclasses are mocks — operator logic is pinned via source-level/`ast` tests (see `tests/moodboard/`, `tests/test_job_queue_download.py`).
- The root `conftest.py` imports the REAL `numpy`/`PIL` before collection: `modules/testing/mock_bpy` stubs third-party modules only when ABSENT from `sys.modules`, so without the preload the first importer decided whether PIL was real for the whole session.
- Config: env vars in `.env` (copy `.env.example`; never commit `.env`) → `scripts/unix/settings.sh` → `scripts/generate_config.py` emits runtime `mixar.json`. C++ env header generated at `source/creator/mixar_env_config.h`. `MIXAR_ENV=Prod` targets `https://api.mixar.app`; `Dev` targets a dev backend and is the only env where dev-bypass credentials are allowed (the build aborts otherwise).
- **CUDA/OptiX is an `.env` switch** (`MIXAR_CUDA`, `MIXAR_CUDA_BINARIES`, `MIXAR_CUDA_ARCH`), resolved in ONE place — `cmake/mixar_overrides.cmake` reads the env vars `settings.sh`/`settings.bat` export. `MIXAR_CUDA=0` drops CUDA, OptiX and the Cycles GPU kernels; `MIXAR_CUDA_BINARIES=0` keeps GPU support but skips the precompiled cubins; `MIXAR_CUDA_ARCH=sm_89` narrows them to one card. The cost avoided is `WITH_CYCLES_CUDA_BINARIES` (nvcc compiles the Cycles kernel once per architecture in `CYCLES_CUDA_BINARIES_ARCH`, ten by default), which dominates a CLEAN build but saves nothing on an incremental rebuild; such a build renders Cycles on CPU only — a local-dev choice, never a release one. `build.bat` normalizes the same variables only to invalidate a CMake cache configured the other way (it skips configure once build files exist; `build.sh` re-configures every run).

### GUI E2E: the QA harness (MISSION-CRITICAL — this is how features ship)

The QA harness drives the REAL built app like a human — semantic clicks by operator-id/prop/surface (no pixel guessing), drags, file drops, targeted screenshots you must actually READ — and runs replayable E2E scenarios (agent chat, Agent Bubble custom targets, moodboard graph, Director timeline, full image→3D→retopology pipeline). **A feature is DONE only when the running app has proven it: state asserts AND vision, plus a scenario left behind.** Before any feature work, read the playbook:

- Harness: private repo `github.com/Mixar-AI/mixar-qa-harness` — clone anywhere and export the path as `$QA_HARNESS`. Read `README.md` (architecture + gotchas), `SHIP_LOOP.md` (the build→drive→verify→encode→ship contract), `UX_CHECKLIST.md` (checkable "looks right" criteria).
- In-app C++ half (introspection RNA, custom-surface targets, drop hook) lives in THIS repo's `develop`, so every branch cut from it is drivable — build Dev.
- Run: `cd "$QA_HARNESS" && ./run_qa_app.sh` then `python3 driver/qa_client.py status`; full suite `./run_scenarios.sh` (spends real credits; one isolated app reloads clean startup state between scenarios); MCP tools available as the `mixar-qa` server.
- New custom-drawn UI is unshippable until it exports QA targets (`Mixar_qa_register_target_provider` — read the surface's OWN hit-test geometry, never duplicate it).

## Code Rules

- No file larger than **500 lines** — split aggressively. Use C++ for performance-critical paths.
- Module layout (strict): `constants.py` at module root; `core/` for logic; `ui/` for auto-discovered UI split into `properties/`, `operators/`, `panels/`, `menus/`, `lists/`. **Properties and operators stay in separate folders.**
- Cross-module shared code goes in `modules/common/` (`common/utils` for utilities).
- **Always update this guide** when features are added/modified/deleted.
- Branch names follow the table in `CONTRIBUTING.md` — lowercase kebab-case, most specific prefix wins (`bugfix/` over `task/` for a bug fix).
- **The keyconfig-reload rule**: custom C region keymaps and any C-registered default-keyconfig binding must ALSO be registered in the addon keyconfig (Python side), never only via C `WM_keymap_add_item` — a GUI keyconfig preset reload wipes C-registered items. Applies to agent_scene_strip, chat select/copy/paste, Director `F` capture, and anything new.
- Upstream is pinned at Blender `v5.2.0`; Mixar C++ is wrapped in `namespace blender` (interface files in `blender::ui`), DNA lists are `ListBaseT<T>`, allocation is `MEM_new*`, runtime operator pointer props use `RNA_def_pointer_runtime`, and animation access goes through the ID's own channelbag via `common/utils/animation.py` (never `Action.fcurves`). Merging `develop` brings 5.0-shaped code that must be re-ported to these conventions.

Project layout:

```text
.env.example                       # environment config template (copy to .env)
scripts/generate_config.py         # emits runtime mixar.json at build time
src/scripts/mixar/
├── bootstrap/                     # startup modules (agent_connection, paint_module, …)
├── config/                        # logging + config persistence
└── modules/{module}/
    ├── constants.py
    ├── core/                      # logic
    └── ui/{properties,operators,panels,menus,lists}/   # auto-discovered
src/source/blender/                # C/C++ overlay
```

## Bootstrap & Registration

`src/scripts/startup/bootstrap/__init__.py` loads everything in 4 phases:

1. **Package setup** — synthetic packages for `src/scripts/mixar/` (no `__init__.py` needed in most subdirs).
2. **Network** — `modules/common/network.configure_network()`: exports the resolved proxy to the environment and installs the OS trust store (`truststore`) by replacing `ssl.SSLContext`. Must precede every bootstrap module — only contexts created afterwards are affected.
3. **Bootstrap modules** — `src/scripts/mixar/bootstrap/*.py`, each with `register()`/`unregister()` (agent connection, paint module, generation catalog cache, update checker, sandbox supervisor, etc.).
4. **UI auto-discovery** — every file under `modules/**/ui/` is loaded in time-budgeted (~4ms/frame) batches: properties first (priority 0), then operators/core (1), then panels/menus/headers (2).

Rules: expose a `classes` tuple and let the fallback mechanism register it — hand-write `register()`/`unregister()` only when genuinely needed. For cross-directory property dependencies, drive import order via the module's `__init__.py` (reference: `paint/__init__.py`).

## Modules (`src/scripts/mixar/modules/`)

| Module | Purpose |
|--------|---------|-----|
| **paint** (largest) | Layer-based texture painting: node trees, modifiers, baking, procedural materials/MatGen, decals, UDIM, vertex colors, asset export; agent-facing layer-stack tools in `paint/core/agent_tools` |
| **addon_project** | Blender-local production add-on workspace driven by the versioned `addon_project_v1` RPC |
| **space_mixie_chat** | Agent chat: WebSocket JSON-RPC + SSE streaming, reconnect-resume, sandboxed script execution, `llm.request` local-LLM relay, project/global rules, @-mention autocomplete, feedback stars, export lane, batched choice wizard, message copy, paste, attachments, voice |
| **agent_bubble** | The Agent island: floating always-on-top chat window with tabs (Agent, 3D, Media, Gaussian Splat, My Generations, Queue), elongated pill resting state, hover collapse; shares ConnectionManager/message store with space_mixie_chat |
| **scribble_mark** | The viewport half of Scribble plus the coordinator that makes Scribble ONE mode (`core/scribble_mode.py`) |
| **agent_viewport_lock** | "Agent working" halo + input-block modal, keyed to the mode the *running* turn started in (`mixie_chat_active_turn_mode`); toasts pass through |
| **agent_scene_strip** | Bottom View3D region (C++ `view3d_agent_strip*`) with live tiles of non-active scenes; keymap in addon keyconfig |
| **moodboard** | Reference boards + node canvas, catalog-driven generation sidebar (Image Gen, AI Render, Model Gen, Texture Gen, Scene Gen, Character Parts, Retopology, UV Unwrap, Mesh Segment, Auto Rig, Video Gen, World Labs + Queue), turnaround/multi-view image-to-3D, clipboard, scene recon, annotations, SAM3 character components, Gaussian splats |
| **director** | Phase-zero camera directing as a viewport mode: native C++ Cinema Mode surface plus gate/popups/timeline over Python-owned operators |
| **hunyuan** | 3D generation enqueue helpers: text/image→3D, retopology (Hunyuan/Tripo engines), UV unwrap, auto-rig (`core/animate_enqueue.py`) |
| **common** | API clients (`common/api/services/`), content-free UX telemetry (`common/analytics`; the client stamps `x-telemetry-consent` on all HTTP requests and the WS handshake, so the Share Usage Data toggle also governs backend-emitted events like `generation.submitted`), WebSocket infra, notifications, versioning, self-updates, job_queue, generation_params, usage, network |
| **auth** | OAuth PKCE with native keyring (macOS Keychain, Windows Credential Manager). Browser SSO callback (`core/sso.py`) is a threaded loopback server with a per-connection read timeout (endpoint-security agents connect without sending a request); `SSO_LOGIN_TIMEOUT_S` (300s) covers corporate IdP + MFA; the login operator has a scoped UI watchdog. Transport failures return `failure_kind` + a support-coded message via `common/network` |
| **byok** / **local_models** | Bring-your-own-key provider settings (cloud catalog, OpenRouter, Codex, Local); zero-setup local llama.cpp runtime |
| **operation_history** | Local JSONL log of agent scripts + curated manual ops; agent queries via `core/tools.py:run_tool`; 15-day prune |
| **scene_graph** | Lazy per-scene agent-readable object graph, queried via `core/tools.run_tool` |
| **onboarding** / **plugin_import** | First-run GPU-rendered tour cards; one-click import of the user's vanilla-Blender plugins |
| **workflow** | Zen/Engine dual-mode workspace UI, the topbar slider and Mixar topbar widgets |
| **asset_search** / **mesh_segment** / **texel_density** / **uv_editor** / **space_texture_sets** / **space_mixie** | Asset embedding search + the "Mixar Generations" archive; SAM segmentation; texel density; UV workspace; texture set management; Mixie space |
| **testing** | Legacy embedded test suite (explicit opt-in) |

## Generation Catalog & Dynamic Params

- `bootstrap/generation_catalog_cache.py` + `bootstrap/generation_catalog/{storage,queries}.py` — ETag-revalidated cache of `GET /api/v1/generation-catalog` (capabilities → services → models → param schemas, styles, credit costs); persisted to disk so panels render instantly; cleared on logout.
- `modules/common/generation_params/` — builds one PropertyGroup per (service, model) from schemas, attached to **WindowManager** (safe re-registration, no .blend persistence). `draw_service_params()` renders; `collect_params()` returns the payload dict; `core/assemblers.py` puts params in `payload["params"]` (snake_case). **Never hardcode param names** — the backend adapters own all vendor mapping; never build provider shapes client-side.
- Every catalog-driven tab keeps its legacy hardcoded UI as the offline/pre-auth fallback — **except** catalog-only capabilities (AI Render, Auto Rig, Video Gen, World Labs, Character Parts), which stay hidden until the backend publishes an enabled service/model and have no hardcoded submit fallback. Generate operator `bl_idname`s and `scene.hunyuan.*` prop groups are **frozen agent contracts** — don't rename.

## Agent System (backend-driven)

Backend runs a LangGraph orchestrator (Claude Sonnet 4.6 primary, Gemini 3.1 Pro fallback) with 18 tool domains / 200+ tools covering modeling, texturing, UV, rigging, particles, scene management and layer painting, and 12+ workflow modes (MODELING, TEXTURING, RIGGING, UV_UNWRAP, SCENE, LAYER_PAINTING, …) that filter which tools the LLM sees. The layer-painting tools call the Blender-side `paint.core.agent_tools` package to initialize Mixar Paint projects, apply Patina layered manifests, search procedural libraries, queue MatGen jobs by pipeline alias, and add procedural materials through the real layer stack. Tool execution: LLM → backend validates → Blender script over WebSocket → script reads `__PARAMS__`, emits `print("__RESULT__" + json.dumps(...))` → result returns to LLM. Client-side execution runs through `space_mixie_chat/core/main_thread_executor.py` / `core/executor.py`. The safe executor exposes `hashlib` and `struct` for local content digests and deterministic binary packing in first-party transaction scripts; filesystem, process, and unrestricted network modules remain blocked.

## Cross-cutting Patterns & Gotchas

- **Handler pattern**: depsgraph handlers set flags → `bpy.app.timers` do the work. Never do heavy work (or property writes) in draw callbacks. A draw or layout callback must never resize an OS window or re-run `ED_screen_refresh` (see the agent_bubble doc).
- **Singleton + daemon threads** for persistent connections (ConnectionManager WebSocket). Background threads must not touch `bpy`; marshal to the main thread via timers. `on_connected` runs on the WebSocket thread.
- **atexit cleanups must not touch `bpy` data** (pinned by `tests/test_shutdown_hooks_atexit.py`): `BPY_python_end` runs *after* `BKE_blender_free()` in `WM_exit_ex`, so an RNA/ID-property write or `draw_handler_remove` there is a use-after-free. `shutdown_hooks._run_all_cleanups` forwards `app_exit` so UI-side cleanup is skipped on that path; thread/process/socket teardown is what atexit is for.
- **Network contract**: never hand-roll `verify=`/`proxies=`/`sslopt=` at a call site — trust and proxy are process-wide (startup phase 2) so all five bundled clients (`requests`, `httpx`, `urllib`, `http.client`, `websocket-client`) agree. Catch `requests.exceptions.RequestException` (or the client's equivalent) and route it through `classify_network_error` (→ `NetworkFailure` with `NET-*` support codes) + `log_network_failure`; generic "Unable to connect" strings are banned (pinned by `tests/network/`). Explicit CA bundle = plain OpenSSL with `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`/`WEBSOCKET_CLIENT_CA_BUNDLE` exported; otherwise `truststore`; Linux without a system bundle falls back to certifi. PAC and SOCKS are unsupported by design.
- **Config persistence** (`mixar/config/config.py`; pinned by `tests/test_config_persistence.py`): the bundled `<install>/<blender version>/config/mixar.json` is BUILD-GENERATED, READ-ONLY input (on Windows the MSI puts it under `C:\Program Files`; macOS updates replace the whole `.app`). Every key a running app persists (`ui_mode`, `share_usage_data`, the fallback `device_id`) goes through `add_config` into the per-user overlay `bpy.utils.user_resource('CONFIG')/mixar/mixar.json`, which holds ONLY keys written that way; reads merge the overlay over the bundled defaults. Never write into `resource_path('LOCAL')`. `_write_config_file` exclusive-creates its own temp name with a bounded retry and no `tempfile.mkstemp` (which on Windows retries `TMP_MAX` times on a `PermissionError` when `os.access(dir, W_OK)` is true); a write failure returns False at once and the in-memory value still applies.
- **Headless sandbox supervision**: the parent Mixar process spawns a background sandbox child with platform-specific process flags; Windows children use Win32 process APIs for parent liveness checks.
- **Custom C++ editor spaces**: `space_mixie_chat`, `space_agent_bubble`, `space_mixar_properties`, `space_mixar_layers`, `space_mixar_assets`, plus the native chat renderer (markdown, thinking visualization, hit testing, thumbnails) and View3D overlays (Director, agent strip, gizmos). Authentication is cross-platform keyring + a local OAuth PKCE callback server.
- **DRW offscreen passes reset the region framebuffer viewport/scissor** — capture and restore manually or the region renders black.
- **Project-file drop contract**: `.mixar` is classified as `FILE_TYPE_MIXAR`, not `FILE_TYPE_BLENDER`; `editors/space_api/mixar_file_drop.cc` registers an explicit whole-window dropbox that routes projects to the standard Open / Link / Append choice.
- **Safety contracts**: backend-authoritative option lists fail closed (empty list → disabled, never resurrect hardcoded services); feedback locks only after confirmed 2xx; BYOK keys are transient `SKIP_SAVE` fields; terminal queue states release large payloads but keep lightweight history; multi-view/turnaround submits refuse loudly rather than degrading to a single image.
- **C++ overlays of note**: `rna_main_api.cc` (kill preview jobs before `bpy.data.*.remove()` frees IDs), `py_capi_utils.cc` (per-thread GIL check), agent-bubble window lifecycle in `wm_files.cc`/`wm_window` (bubble windows never serialized; GHOST pointers invalidated on close AND free), `space_node/node_templates.cc` (hides Mixar-internal node groups from the socket menu).
- `mixie_chat_free()` clears process-global caches and runs for ANY freed Main (including temp Mains) — any new global cache cleared there needs a self-heal check on the draw path.

## Self-Update (`modules/common/updates/`)

One **Restart & Update** click stages the release installer, spawns a detached helper, quits, and relaunches; the downloads page is the fallback. Decisions live in `core/install_flow.py` (`plan_restart`, `apply_and_restart`) so they are testable under the `bpy` mock; config is `mixar.json` → `updates.{channel,check_delay_seconds,auto_download,downloads_url}`. Install paths carry no version (pinned by `tests/test_update_packaging_paths.py`). Windows staging lives in `%ProgramData%\Mixar\Updates` (a per-machine MSI runs elevated and must read the installer from a shared location); the installer is trusted only after the backend `sha256` matches AND its signature matches the running app's; the detached helper never lives in the install directory; a quit that does not happen is recovered by a 15s watchdog that returns state to READY.

## Repo Docs Map

- `README.md` — public build-from-source guide and licensing.
- `CONTRIBUTING.md` — contribution status, development rules, and the **branch naming table** (use the most specific prefix: `feature/`, `bugfix/`, `chore/`, `refactor/`, `task/`, …).
- `SECURITY.md` — vulnerability reporting. `NOTICE.md` — third-party notices.
