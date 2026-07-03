<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# `space_mixie_chat` — Plugin Agent Client Architecture

> Companion to `mixar-backend/modules/agent/ARCHITECTURE.md`. This doc covers the **plugin side** of the agent — the two networked channels, the main-thread executor, the dual sandbox, scene routing, the SSE → slot → C++ render pipeline, undo / render / file-load guards. Hold this open alongside the backend doc when working on cross-cutting changes.

## TL;DR

The plugin is *both* the agent's UI (a custom in-tree C++ Blender editor + Python message/state shell) *and* the agent's execution arm (it runs the `bpy` scripts the backend emits). Two simultaneous network channels connect plugin and backend:

- **HTTP/SSE** — per-turn, plugin → backend (`POST /agent/chat`), backend → plugin (slot events). Lives only for the turn duration.
- **JSON-RPC 2.0 over WebSocket** — long-lived, bidirectional, backend → plugin (`blender.execute_script` + tool lifecycle notifications), plugin → backend (responses + `system.handshake` + `system.ping` + `notifications.sync`).

Both channels share the same JWT auth, refreshed through a single mutex-guarded helper (`refresh_access_token_shared` — K5).

The plugin's job in one sentence: **receive scripts on a WS thread, run them on Blender's main thread, push results back, render the streaming chat into a Blender editor while it happens.**

## Why this design is worth understanding

A naive implementation of "agent that runs `bpy` code" would call `bpy.ops.*` from whatever thread the network handler is on. That segfaults Blender within seconds — `bpy` is strictly main-thread. So the plugin needs:

1. A **queue** that crosses the WS-receive thread / main thread boundary.
2. A **main-thread timer** that drains the queue and runs each script with `bpy` access.
3. A **second sandbox** inside the executor in case the backend sandbox missed something.
4. A **render guard** that defers execution while Blender is rendering (another known segfault path).
5. **Scene-aware routing** so a script for session A runs against scene A even if the user is currently viewing scene B.
6. **Exception safety** at every layer because Blender's timer system silently swallows unhandled exceptions, killing the timer permanently.

Each of these gets its own layer below.

## Topology

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          BLENDER PROCESS                                      │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  C++  space_mixie_chat editor          mixie_chat_messages_render   │    │
│  │       (in-tree Blender editor)         + layout + content slots     │    │
│  │       scene.mixie_chat_messages  ←─── chat persists per scene       │    │
│  └────────────────────────────────────────┬──────────────────────────────┘    │
│                                            │ slot updates                    │
│                                            ▼                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │   Python: space_mixie_chat.core                                      │    │
│  │                                                                       │    │
│  │   sse_handler.py ────────► slot_processor.py ────► bubble PropertyGrp│    │
│  │   (per-scene SSE thread)   (mutate mixie_chat_messages on main thr)  │    │
│  │           ▲                                                           │    │
│  │           │ slot events                                              │    │
│  │           │                                                          │    │
│  │   jsonrpc_client.py ──────► main_thread_executor.py ──► executor.py │    │
│  │   (WS thread)                (queue + main-thr timer)   (script run)│    │
│  │           ▲                                                          │    │
│  │           │ requests                                                  │    │
│  └───────────┼──────────────────────────────────────────────────────────┘    │
│              │                                                               │
└──────────────┼───────────────────────────────────────────────────────────────┘
               │
       ── NETWORK ──
               │
┌──────────────▼───────────────────────────────────────────────────────────────┐
│                         BACKEND (mixar-backend)                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

Three IDs identify what:

- `instance_id` (UUID v4, `WindowManager.mixie_instance_id`) — one per **Blender process**. Survives `.blend` open/close.
- `session_id` (UUID v4, `scene.mixie_session_id`) — one per **conversation**. One per scene.
- `bubble_id` (server-generated) — one per UI bubble within a session. Cached in Redis as `todo_bubble:{session_id}` so cross-stream todo updates land in the same bubble.

## Module map

```
src/scripts/mixar/modules/space_mixie_chat/
├── constants.py              Enums (SessionState), endpoint paths, timeouts.
├── core/
│   ├── connection_manager.py    Singleton WS lifecycle (connect/disconnect/reset).
│   ├── jsonrpc_client.py        WS client (tool execution channel). B3/B4/B6/B8/K5.
│   ├── jsonrpc_auth.py          AuthBackoffManager + shared JWT refresh helper (K5).
│   ├── sse_handler.py           Per-scene HTTP SSE client (agent stream).
│   ├── main_thread_executor.py  Request queue + main-thread timer (B3/B6/B8/K1/render guard).
│   ├── executor.py              ScriptExecutor — second sandbox + handler snapshot/restore.
│   ├── sandbox_validator.py     AST validator (mirrors backend, runs again on plugin).
│   ├── sandbox_modules.py       RESTRICTED_OS / RESTRICTED_TEMPFILE / RESTRICTED_BASE64 wrappers.
│   ├── sandbox_builtins.py      Safe __builtins__ (no eval/exec/compile/__import__).
│   ├── session.py               Per-scene SessionManager (state + active_sessions registry).
│   ├── slot_processor.py        Apply SSE slot events to scene.mixie_chat_messages.
│   ├── queue_processor.py       SSE event queue drained on main-thread timer (K2).
│   ├── undo_guard.py            Snapshot/restore chat across undo/redo (K4 try/finally).
│   ├── animation_manager.py     Loader-spinner animation timer (K2 active-scene-first).
│   ├── file_handlers.py         load_pre / load_post cleanup chain (K6 exception-safe).
│   ├── markdown_parser.py       Mistune-based markdown → segment AST for C++ rendering.
│   ├── markdown_preprocessor.py Pre-AST transforms (code-block numbering, etc.).
│   ├── image_utils.py           Moodboard image encoding for multimodal uploads.
│   ├── generation_poller.py     Async generation result polling.
│   ├── performance_metrics.py   Client-side metrics shipped to the backend.
│   └── message_helpers.py       Message construction helpers.
├── ui/                          Blender Python panels + operators (UI shell).
│   └── operators/
│       ├── chat_ops.py             Main "send message" operator.
│       ├── auth_ops.py             Login flow.
│       ├── screenshot_ops.py       Viewport capture.
│       └── chat_special_ops.py     Approve / abort / modify operators.
└── ARCHITECTURE.md           This file.

Related but outside space_mixie_chat:
src/scripts/mixar/modules/agent_bubble/      Floating chat bubble (separate UI shell).
src/scripts/mixar/modules/moodboard/         Moodboard image management.
src/source/blender/editors/space_mixie_chat/ C++ in-tree Blender editor (rendering).
```

## The two channels

### Channel A — JSON-RPC 2.0 over WebSocket

**File:** `core/jsonrpc_client.py` (~700 lines). One background thread (`MixarJSONRPCWS`) per Blender process. Long-lived; same socket carries every tool call for the session.

**Connect path:** `_run_loop` → `_do_connect` → `_perform_handshake` (sends `system.handshake` with `blender_version`, `addon_version`, `capabilities`) → `_receive_loop`.

**Reconnect:** exponential backoff (1s → 30s). After three consecutive auth failures the loop stops — see `AuthBackoffManager` in `jsonrpc_auth.py`. If the token hasn't changed across the backoff window, the loop stops early so we don't hammer the auth backend with a stale token.

**Receive-loop hardening (B3/B4):** every per-message handler is wrapped so unparseable JSON or a handler exception logs + continues. Pre-B4, a single bad message killed the loop and orphaned every pending callback.

**On reconnect handshake completion:** calls `flush_pending_responses()` (defined in `main_thread_executor`) to replay any tool responses that were buffered while disconnected. See B6 + K1.

**Auth refresh (K5):** when a 401 fires, `_try_refresh_token` delegates to `refresh_access_token_shared` (mutex + 2s result cache) in `jsonrpc_auth.py`. The SSE handler uses the same helper. Both channels stay in lock-step on token rotation.

### Channel B — HTTP/SSE

**File:** `core/sse_handler.py`. One short-lived `httpx.Client` per agent turn. Reopened per `/agent/chat` or `/agent/input` call.

**Per-scene handler registry** — `_sse_handlers: dict[scene_name, SSEStreamHandler]`. Multi-scene Blenders run concurrent SSE streams, each tied to its scene.

**Two event formats supported** (the parsing layer normalises):
- **Slot-based** (current) — event has `bubble_id`, event_type set to `"slot"`. Routed through `slot_processor`.
- **Legacy** — event has `type` field. Older code path still tolerated for back-compat.

**Timeouts:** `connect=10s`, `read=SSE_READ_TIMEOUT` (>600s to outlast backend tool timeout), `write=60s` (covers base64-image uploads), `pool=10s`.

**401 handling:** read response, call shared `_try_refresh_token`, retry once with new token. If refresh fails, surface error.

## Main-thread executor — the linchpin

**File:** `core/main_thread_executor.py`. The most subtle file in the plugin.

The contract: scripts arrive on the WS receive thread; `bpy` runs on the main thread. The executor bridges them via a queue + a `bpy.app.timers.register`-driven timer.

```
WS receive thread                Main thread (Blender event loop)
─────────────────                ─────────────────────────────────
on_script_execute()
    │
    ▼
queue_script_request()           bpy.app.timers.register(_process_one_request, 0.01)
    │
    ▼
_request_queue.put((id, script, tool, session))
                                 ──── 10ms later ────
                                 _process_one_request()  [B3 outer guard]
                                     │
                                     ▼
                                 drain_pending_events()  (SSE first)
                                     │
                                     ▼
                                 wait for execution gate (50ms post tool_start)
                                     │
                                     ▼
                                 _is_render_in_progress()? defer-and-retick
                                     │
                                     ▼
                                 dequeue (id, script, tool, session)
                                     │
                                     ▼
                                 [B3 inner guard around the rest]
                                     │
                                     ▼
                                 switch bpy.context.window.scene → target
                                     │
                                     ▼
                                 ScriptExecutor.execute(script)   ← see "executor" below
                                     │
                                     ▼
                                 restore original scene
                                     │
                                     ▼
                                 jsonrpc_client.queue_response(id, result)
                                     │
                                     ▼
                                 OR _buffer_pending_response(...) if disconnected
```

### Defensive layers

| Layer | Why |
|-------|-----|
| **B3 outer guard** (`_process_one_request`) | Blender's `bpy.app.timers` silently eats exceptions; without this, one error kills the timer forever. We catch + log; in-flight request still gets an error response. |
| **B3 inner guard** (`_execute_dequeued_request`) | Once we've dequeued a request, any exception before `queue_response` would leave the server's `tool_use` without a `tool_result`. Inner try sends an error response on failure. |
| **B8 queue-full** | `_request_queue.put_nowait` raising `Full` triggers an explicit error response to the server, not a silent drop. |
| **B6 pending-response buffer** | If `client.is_connected` is False at response time, stash in `_pending_responses: dict[id, (queued_at, session_id, result)]` with TTL 900s, max 256 (LRU evict). Flushed on next handshake. |
| **K1 session-tagged buffer** | B6 entries carry the originating `session_id`. On flush, drop entries whose session is no longer present in any open scene (the user reloaded a different .blend while disconnected). |
| **Render guard** | `_is_render_in_progress()` checks both `bpy.app.is_job_running('RENDER')` and a handler-driven `_rendering_now` flag (set by `render_init`, cleared by `render_complete`/`render_cancel`). Peek-and-defer pattern: leave the script on the queue, re-tick later. Closes the depsgraph-mutation-mid-render segfault path. |
| **Scene routing per session** | The backend addresses every script with a `session_id`. The constant `agent:<connection>` (or empty) session is **non-pinned**: it matches no scene and runs against the user's active window scene (normal / sandbox mode). Any *other* non-empty session is a **per-scene** target — the user's main scene's `mixie_session_id` (a UUID) or an `agentlane:<parent>:<n>` lane scene (scene-build mode). Per-scene: switch `window.scene` to the matching scene, execute, restore — all in one timer tick (no redraw, no flicker). Prefix helpers live in `constants.py` (`is_non_scene_routing_session`, `is_lane_scene`). |
| **Per-scene hard-fail** | If a per-scene session resolves to **no** scene, the script is **rejected** (error response `no scene for session <id>`) instead of silently running in the active scene — that fallback could clobber the user's work in the wrong scene. Non-pinned `agent:`/empty sessions keep the active-scene-follow behavior. |
| **Foreground-scene restore** | After a per-scene/lane script flips away, `window.scene` is restored to the user's tracked *foreground* scene (`_user_foreground_scene_name`, captured whenever a non-pinned script runs), **not** "whatever was active when the script started" (which could be a throwaway lane scene). If the tracked scene was deleted, falls back to any non-lane scene — never a lane. |
| **Execution gate (50ms)** | `_execution_gate_until` defers script running by 50ms after `tool_start` so the chat UI has time to render the planning bubble *before* the executor blocks the main thread. Set via `gate_execution(0.05)`. |
| **Session-not-active guard** | Narrow race where `load_pre` flushed the session between queue and execute — drop the script and ack the server with an error. |
| **Asset prefetch hold** (`core/script_prefetch.py`) | Heavy texture-apply scripts (`create_layered_material`) embed their asset URLs in the script text. `queue_script_request` starts downloading them immediately on the WS thread (daemon threads, global 8-slot semaphore); `_process_one_request` holds the dequeued script in `_held` — one cheap `ready()` check per tick, UI fully responsive — until the cache is warm or the 90s wait cap passes. Execution then pays only image decode + node build, never the network. FIFO is preserved (later scripts wait behind the held one, their own prefetches already running), and the in-build downloads (with their fail-fast negative cache) remain the fallback. |

## ScriptExecutor — the second sandbox

**File:** `core/executor.py`. The backend's `validate_bpy_script` is the first line; the plugin's `ScriptExecutor` is the second. Either can reject.

`ScriptExecutor.execute(script)`:

1. **AST validation** — `validate_script_ast` in `sandbox_validator.py`. Denylist of forbidden constructs + reflection-escape blocking (matches the backend's S2 hardening) + dangerous attribute checks. Raises `SandboxViolationError` on violation.
2. **Restricted module wrapping** — `os` → `RESTRICTED_OS` (no `system`, no `popen`, no exec family), `open` → `restricted_open` (paths gated), `tempfile` → `RESTRICTED_TEMPFILE`, `base64` → `RESTRICTED_BASE64`.
3. **Safe builtins** — `get_safe_builtins()` returns a curated `__builtins__` dict; no `__import__`, no `eval/exec/compile`.
4. **Handler snapshot** — captures `bpy.app.handlers` lists (`depsgraph_update_post`, `frame_change_post`, `load_pre`/`load_post`, `object_bake_*`, ...). After execution, restores them so scripts can't leak persistent handlers across sessions.
5. **stdout/stderr capture** — `StringIO` redirection. Parses `__RESULT__` prefix lines into `return_value` (the cross-process result protocol — backend's tools rely on this).
6. **Scene-change diffing** — tracks `created_objects`, `modified_objects`, `deleted_objects` by pre/post object set diff. Returned in the response envelope.
7. **`sanitize_value` on return** — recursively coerces non-JSON-safe types (bpy datablocks, IDs, mathutils Vectors) into JSON-serialisable forms.

Result envelope sent over JSON-RPC:

```json
{
  "success": true,
  "output": "<stdout>",
  "created_objects": ["Cube.001"],
  "modified_objects": [],
  "deleted_objects": [],
  "<__RESULT__ dict fields flattened in here>": "..."
}
```

## SSE → UI: `slot_processor.py` + the C++ editor

When an SSE event arrives, `_on_event` dispatches to `SlotEventProcessor.apply_event(event_data, scene)`:

1. **Bubble resolve** — `_get_or_create_bubble(bubble_id, scene)` searches `scene.mixie_chat_messages` for a `PropertyGroup` with matching `bubble_id`. Creates one if not found; removes any optimistic-UI placeholder loader.
2. **Per-slot apply**, each in its own try/except so one bad slot never blocks the others:

   | Slot | Maps to |
   |------|---------|
   | `input_type` | `bubble.input_type` (controls which action buttons render) |
   | `loader` | `bubble.loader_visible`, `loader_texts` (JSON-encoded), `loader_rotate_ms`. Starts/stops the animation timer. |
   | `content` | Appended / set / cleared markdown text. Parsed incrementally for C++ rendering (see `markdown_parser`). |
   | `ephemeral` | Temporary FIFO display — last N lines of thinking / streaming text. Cleared on stream complete. |
   | `todo` | `bubble.todo_items` collection (status enum: PENDING / IN_PROGRESS / DONE / FAILED). |
   | `actions` | `bubble.action_items` (buttons: PRIMARY / DEFAULT / DANGER style). |
   | `images` | `bubble.image_items` (gallery with url + alt + caption + thumbnail). |

The C++ editor (`src/source/blender/editors/space_mixie_chat/`) renders `scene.mixie_chat_messages` on each redraw — `mixie_chat_messages_render.cc` walks the collection, `mixie_chat_messages_layout.cc` computes layout, `mixie_chat_slots.cc` dispatches per-slot rendering. Markdown content goes through `mixie_chat_markdown_intern.hh`. Drag-drop of moodboard images is wired in `mixie_chat_dragdrop.cc`.

Persisting chat as scene properties means **chat survives `.blend` save/load** for free. It also means `undo_guard.py` snapshots all scenes' chat collections before every undo/redo.

## Session lifecycle

**File:** `core/session.py`. `SessionManager` is a stateless accessor over per-scene properties:

| Property | Type | Purpose |
|----------|------|---------|
| `scene.mixie_chat_state` | enum | `OFFLINE` / `CONNECTING` / `IDLE` / `BUSY` / `MODIFYING` / `AWAITING_INPUT` |
| `scene.mixie_chat_is_busy` | bool | Derived flag for the C++ rendering path (faster than parsing the enum). |
| `scene.mixie_session_id` | UUID v4 | Conversation identifier. |
| `WindowManager.mixie_instance_id` | UUID v4 | Blender process identifier. |

**Active-scenes registry:** class-level `_active_scenes: set` tracks scene names whose state is `BUSY/MODIFYING/AWAITING_INPUT`. Updated only from the main thread under `_active_scenes_lock`. Background threads read it (e.g. `on_script_execute` checks `has_active_session()` to reject stray scripts after a session ends).

**Session start (`start_session(scene, user_request)`):** generates a new `session_id` only if none exists; otherwise continues. Sets state to `BUSY`. Returns the session_id.

## Undo guard

**File:** `core/undo_guard.py`. Blender's undo system rolls back scene properties — including `mixie_chat_messages`. Without intervention, every undo erases chat. The guard installs four `@persistent` handlers:

- `undo_pre` / `redo_pre` → `_snapshot_all_scenes()` deep-copies every scene's chat collection.
- `undo_post` / `redo_post` → `_restore_all_scenes()` writes them back. K4 fix wraps this in `try/finally` so `_saved_messages` always clears, even on restore failure.

Snapshot covers everything: `sender`, `text`, `bubble_id`, all loader fields, content/ephemeral, attachments, todo_items, action_items, image_items.

## Render guard (depsgraph segfault defense)

**Location:** `main_thread_executor.py`. Blender hard-crashes (segfault) when a script mutates scene/depsgraph state on the main thread *while* a render is actively writing frames — the render thread holds depsgraph state that concurrent mutations corrupt. Observed in production with a render_animation call followed by an orchestrator-emitted scene-edit script.

**Two independent signals**, checked together:

1. `bpy.app.is_job_running('RENDER')` — Blender's own job tracker (since 2.93). Canonical.
2. Handler-driven `_rendering_now` flag — set by `render_init`, cleared by `render_complete`/`render_cancel`. Belt-and-suspenders for the brief window in some Blender builds between `render_init` and the job appearing in the WM job list.

Either says "rendering" → defer-and-retick: leave the script on the queue, return `TIMER_INTERVAL`, re-check next tick. The post-dequeue path re-checks too (narrow race between peek and dequeue).

## File-load lifecycle

**File:** `core/file_handlers.py`. When the user opens a new `.blend`:

- `load_pre` — flush all SSE handlers (`cleanup_all_sse_handlers`), stop the main-thread executor (`cleanup`), clear pending responses, force-OFFLINE all scenes. **K6 fix** wraps each step in `try/except` so a partial failure (a stale SSE handler that refuses to close, etc.) doesn't strand later cleanup steps.
- `load_post` — re-init session state for the newly-loaded scenes (chat messages persisted as scene properties are still there).

## Cross-channel contracts (the invariants)

These are the contracts between the two repos. Breaking any of them on either side causes a class of failures:

- **`__RESULT__` protocol** — all `bpy` scripts that need to return data MUST `print("__RESULT__" + json.dumps(result))`. Plugin executor captures stdout and parses lines beginning with this prefix. Bare expressions at the end of the script are discarded.
- **`mixie_session_id` per scene** — backend addresses scripts to a specific session; plugin routes execution to the matching scene by this property. The non-pinned `agent:<connection>`/empty session runs against the user's active scene; any other unresolved per-scene session is **rejected** (see "Per-scene hard-fail" above), never silently misrouted.
- **Slot event shape** — `loader` / `content` / `ephemeral` / `todo` / `actions` / `images` / `input_type` / `interrupt_data`. Backend `SlotTransformer` emits them; plugin `slot_processor` consumes them. Adding a new slot requires changes on **both** sides.
- **Tool-call pairing invariant** — every `tool_use` the backend emits must get a matching `tool_result`. B5 (RPC timeout), B6 (disconnect buffer), B8 (queue full), B-Mira (invariant guard), B1 (compaction scrub) all defend this from a different angle.
- **JWT shared across both channels** — same token, refreshed in lock-step via `refresh_access_token_shared` (K5).
- **`request_id` uniqueness** — within a connection lifetime. Plugin's `_pending_responses` and backend's tool-call tracking both key on it.

## Where to look for what

| Question | First file to read |
|----------|---------------------|
| Why did a tool call hang forever? | `main_thread_executor.py` (queue, render guard, B3/B6) |
| Why is the bubble showing stale content? | `slot_processor.py` (slot apply) + `markdown_parser.py` |
| Why did Blender just segfault? | render guard in `main_thread_executor.py`, or sandbox bypass in `executor.py` |
| Why did the agent stop responding mid-turn? | `sse_handler.py` (read timeout, 401, [DONE] missing) |
| Why am I getting auth errors on long sessions? | `jsonrpc_auth.py` K5 shared refresh; check both channels hold the same token |
| Why did the chat disappear after undo? | `undo_guard.py` snapshot/restore + K4 try/finally |
| Why did loading a new `.blend` break the agent? | `file_handlers.py` load_pre cleanup + K6 exception-safety |
| Why is the plugin using 15% CPU at idle? | `animation_manager.py` + `queue_processor.py` K2 scene iteration |
| Why didn't my script run? | First check sandbox in `executor.py` + `sandbox_validator.py`; then check session state in `session.py`; then check the render guard. |

## Companion docs

- `mixar-backend/modules/agent/ARCHITECTURE.md` — backend-side companion (graph, agents, middleware, transport).
- `mixar-backend/docs/reviews/AGENT_STUCK_INVESTIGATION.md` — fix rationale for the May 2026 audit.
- `mixar-backend/docs/reviews/AGENT_REVIEW_2026_05_BACKLOG.md` — deferred items + verified false positives.
- The `/Users/rahulmehta/Work/Mixar/rahul-memory/Plans/Mixar Backend Agent Architecture - 2026-05-26.md` plan doc has the full SWOT and prioritised improvement list across both repos.
