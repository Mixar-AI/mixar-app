<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# `space_mixie_chat` — Plugin Agent Client Architecture

The client is both the agent UI and its Blender execution arm. All desktop agent traffic uses one authenticated JSON-RPC WebSocket. The full command/replay contract is in the private `docs/modules/agent-websocket-migration.md` document.

## Transport and module map

- `common/agent_rpc/client.py`: shared settings/command facade; UUID mutation receipts and explicit uncertainty.
- `core/jsonrpc_client.py`: connection state and callbacks; `socket_connection.py` owns reconnect/handshake, `socket_dispatch.py` routes incoming methods, `socket_requests.py` correlates responses/deadlines.
- `socket_writer.py` and `socket_queue.py`: connection-scoped bounded writer, independent of reads.
- `socket_reauth.py`: same-user token rotation; `jsonrpc_auth.py` shares refresh synchronization.
- `composer_send.py`, `chat_payloads.py`, `turn_transport.py`: shared outgoing context and chat/input selection. Answers carry native interrupt IDs; open-run interjections settle through command receipts.
- `turn_events.py`: bounded main-thread inbox for starts, slot payloads and terminal records; per-turn sequence deduplication and replay. `turn_cursor.py` persists the rendered cursor with the scene transcript.
- `queue_processor.py`, `slot_processor.py`: typed payload/state updates and slot rendering shared by both chat surfaces.
- `main_thread_executor.py`, `executor.py`, sandbox modules: existing script execution and safety boundaries.

`instance_id` identifies the process, `session_id` the scene conversation, `run_id` background work spanning turns, `turn_id` one delivery stream, and `bubble_id` a rendered message. New Chat/file teardown fences late events from the previous session. Script responses never replay scene-changing execution.

Requests require `agent_ws_v1`; no HTTP fallback exists. Agent settings, feedback, chat and questions share the socket with tools and `llm.request`. Login/refresh, generation and other non-agent HTTP APIs remain separate. One sequenced `turn_end` completes a delivery stream; reconnect status uses the last applied cursor and reports unavailable history explicitly.

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
                                 drain_pending_events()  (agent stream first)
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
| **Asset prefetch hold** (`core/script_prefetch.py`) | Heavy texture-apply scripts (`create_layered_material`) embed their asset URLs in the script text. `queue_script_request` starts downloading them immediately on the WS thread (daemon threads, global 8-slot semaphore); `_process_one_request` holds the dequeued script in `_held` — one cheap `ready()` check per tick, UI fully responsive — until the cache is warm or the 90s wait cap passes. Execution then pays only image decode + node build, never the network. FIFO is preserved (later scripts wait behind the held one, their own prefetches already running); a prefetch that fails or passes the cap refuses the script with an explicit error rather than falling back to a main-thread download, and only scripts we start no prefetch for (unknown tool, or no extractable asset URL) keep the old in-build path. |

## ScriptExecutor — the second sandbox

**File:** `core/executor.py`. The backend's `validate_bpy_script` is the first line; the plugin's `ScriptExecutor` is the second. Either can reject.

`ScriptExecutor.execute(script)`:

1. **AST validation** — `validate_script_ast` in `sandbox_validator.py`. Denylist of forbidden constructs + reflection-escape blocking (matches the backend's S2 hardening) + dangerous attribute checks. Raises `SandboxViolationError` on violation. `_BLOCKED_DUNDER_ATTRS` is the single list used by BOTH this pass and the wrapped `getattr`/`hasattr`/`setattr` in `sandbox_builtins.py`, and it covers the raw slots (`__getattribute__`, `__setattr__`, `__reduce__`, ...) — without those, `object.__getattribute__(cls, '__subclasses__')` walks past the whole denylist, since `object` is an allowed builtin. Format strings are checked too: `'{0.__class__}'.format(x)` resolves attributes in C, so a blocked dunder inside a replacement field is rejected at the literal.
2. **Restricted module wrapping** — `os` and `pathlib` are **not exposed at all** (importing them is rejected — the real modules grant `os.system`/`os.environ`/`Path.write_text`, a full escape); `open` → `restricted_open` (paths gated), `tempfile` → `RESTRICTED_TEMPFILE`, `base64` → `RESTRICTED_BASE64`, `urllib` → `RESTRICTED_URLLIB`, `string` → `RESTRICTED_STRING` (everything but `Formatter`, whose `get_field()` resolves `"0.__class__.__base__"` with the real getattr and returns the object). Pure-Python stdlib (`math`, `re`, `json`, `collections`, `itertools`, `functools`, `statistics`, `heapq`, `bisect`, `copy`, `textwrap`, `fractions`, `decimal`, ...) is pre-injected into `exec_namespace`; `_restricted_import` derives its allowlist from the namespace keys, so injecting a module is all it takes to make `import x` work — and **not** injecting one is how `runpy` (`run_module("os")` returns the real `os` namespace) and `operator` (`attrgetter` takes the attribute name as a string) stay out. Mirrored backend-side in `mixar-backend` `modules/agent/tools/decorator.py:CLIENT_MODULES`.
3. **Safe builtins** — `get_safe_builtins()` returns a curated `__builtins__` dict; no `__import__`, no `eval/exec/compile`, no `vars`/`globals`/`super`/`__build_class__` (so `class` statements are impossible). `type` and the common exception classes ARE exposed — without them a script cannot write `try/except` at all, and the failure only surfaced after a full model round trip.
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

## agent stream → UI: `slot_processor.py` + the C++ editor

When an agent stream event arrives, `_on_event` dispatches to `SlotEventProcessor.apply_event(event_data, scene)`:

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

### Post-response feedback

On a clean stream completion, `queue_processor.py` exposes feedback only on the
newest completed agent bubble. Thumbs up/down share the copy action row and send
ratings 5/1 through the existing `feedback` WebSocket command; 0 remains unrated.
Votes update locally immediately and can switch without waiting for delivery;
the same selected vote is a no-op. Delivery is best-effort on a sequential daemon
worker to preserve click order. Missing sessions and transport failures stay silent.

The compact Comment action opens an optional editor after a vote. Save (or Enter)
submits and closes immediately; Close preserves the draft; Cancel discards it without
posting. Locally submitted comments remain visible and are preserved when switching
votes. The legacy RECEIVED RNA value means locally submitted; no delivery callback
updates RNA, reopens drafts or shows sending/failure status. Native geometry drives
rendering, hover, clicks and QA targets (`chat_feedback_vote`,
`chat_feedback_comment`) in the island, the sole remaining chat surface.

## Session lifecycle

**File:** `core/session.py`. `SessionManager` is a stateless accessor over per-scene properties:

| Property | Type | Purpose |
|----------|------|---------|
| `scene.mixie_chat_state` | enum | `OFFLINE` / `CONNECTING` / `IDLE` / `BUSY` / `MODIFYING` / `AWAITING_INPUT` |
| `scene.mixie_chat_is_busy` | bool | Derived flag for the C++ rendering path (faster than parsing the enum). |
| `scene.mixie_session_id` | UUID v4 | Conversation identifier. |
| `scene.mixie_run_open` / `scene.mixie_run_id` | bool / str | The backend run behind the chat is still open (workers may build while the turn is IDLE). Single writer: `SessionManager.set_run` (main thread); reader `run_open`. SKIP_SAVE. |
| `WindowManager.mixie_instance_id` | UUID v4 | Blender process identifier. |

**Active-scenes registry:** class-level `_active_scenes: set` tracks scene names whose state is `BUSY/MODIFYING/AWAITING_INPUT` **or whose run is open**. Updated only from the main thread under `_active_scenes_lock` (`set_state` and `set_run` both resync). Background threads read it (e.g. `on_script_execute` checks `has_active_session()` to reject stray scripts after a session ends). Counting the run is what lets a background worker's script land while the orchestrator's turn is IDLE — before it, every such script was refused with "Agent session not active".

### Runs that span turns

Backend contract: `mixar-backend/docs/api/frontend/wakeup-turns.md`. Client pins: `tests/test_open_run.py` (run state, typed payloads, composer) and `tests/test_socket_turns.py` (`agent.turn.*`).

- **Run state** — the typed payload `{"type": "run_status", "run_id", "status": "in_progress" | "completed"}` (first payload of every orchestrated turn and again before its final `complete`) is the run's authoritative signal; `queue_processor._handle_typed_payload` feeds `set_run`. `{"type": "cancelled"}` closes the run. `turn_end` closes the run unless a `run_status` arrived during that turn (older backend / chat-only turn). Typed payloads are settled BEFORE the executor's undo-turn bracket; unknown types are still ignored.
- **Lifetime** — a transient WS drop preserves the run (the backend defers wake-ups until the next handshake); a terminal disconnect, `ConnectionManager.disconnect`, `load_pre`, Stop (`abort_session`), New Chat and a history switch close it. `load_pre` also aborts a scene whose turn is IDLE but whose run is open.
- **Wake-up turns and composer** — `turn_events` applies all delivery streams through the same ordered inbox. `composer_send` chooses a native interrupt answer, open-run interjection or initial chat. Each mutation has a stable command ID and each user bubble has its own delivery hint. Joining a run does not end or replace its active stream.

- **Buttons (C++)** — the floating island shows SEND whenever the composer has text and STOP only while busy with an empty composer (`agent_ui_state.cc` `stop_visible`); the generation-cancel branch is unchanged. **Status** — BUSY reads "Running"; IDLE with the run open reads "Working" (`agent_bubble/ui/header.py`, `status_indicator.py`); the cat pulses while the run is open; the viewport lock stays keyed on BUSY/MODIFYING; the parked auto-resume and the orphaned-turn check skip scenes with an open run.

**Session start (`start_session(scene, user_request)`):** generates a new `session_id` only if none exists; otherwise continues. Sets state to `BUSY`. Returns the session_id.

## Chat history archive

**Files:** `core/chat_history.py` (store), `core/chat_serializer.py` (generic PropertyGroup↔dict snapshot/restore, shared with `export_ops.py`), `ui/operators/history_ops.py` (data + operators), and the **C++-drawn overlay** split across `editors/space_mixie_chat/mixie_chat_history_overlay.cc` (layout + drawing), `mixie_chat_history_events.cc` (clicks/keys/scroll/cursor), `mixie_chat_history_util.cc` (RNA readers + text/glyph helpers) and `mixie_chat_history_intern.hh` (shared constants/colors).

The list UI is a custom screen-space overlay in the chat main region (drawn after `mixie_chat_draw_messages`, like the scroll indicator — so it also appears inside the floating agent bubble): dim scrim + rounded card, "Chats" header with count and a close ✕, an always-focused **search field** (every printable key filters titles case-insensitively; Backspace edits), **date-group section headers** ("Today" / "Yesterday" / "Previous 7 Days" / ...), hover-highlighted rows (accent dot on the open chat, dimmed relative time, delete ✕), **pixel-smooth scrolling** (wheel/trackpad write `history_scroll_target`; the draw eases `history_scroll_px` toward it on the shared anim pump, rows scissor-clipped to the list viewport, slim thumb), **keyboard navigation** (Up/Down move an accent-outlined selection auto-scrolled into view, Enter opens the selection — or the first match while searching — Delete arms/confirms delete, Page Up/Down scroll a page), ESC (disarm → clear search → close) / click-away to close, open fade+slide animation. Contract with Python:

- `WindowManager.mixie_chat_history_visible` (bool) — toggled by `MIXIE_CHAT_OT_show_history` (header history button, which syncs first); the C++ side clears it on ESC / click-away / close ✕ / row open.
- `WindowManager.mixie_chat_history_entries` — runtime mirror of the store (title in `name`, `session_id`, precomputed short `when` label + `group` date-bucket label; a section header is drawn whenever `group` changes between consecutive newest-first rows), rebuilt by `sync_history_entries()` on open and after deletes; C++ only reads it (via RNA, same pattern as `scene.mixie_chat_messages`).
- Row/✕ clicks dispatch `mixie_chat.open_history_session` / `mixie_chat.delete_history_session` with a `session_id` string prop (`WM_operator_name_call_ptr`, same as slot-action clicks; delete is arm-to-confirm in the overlay: first ✕ click (or Delete key) arms the row — red "Delete?" — the second dispatches ExecDefault; any other click or ESC disarms (no OS popup, which anchored its OK button under the clicked ✕)). Overlay state (scroll, search query, keyboard selection, hover/hit rects, panel bounds) lives per surface in `MixieChatRuntime` (`history_*` fields); events are handled first in `mixie_chat_ui_handler` (all keyboard input is consumed while open — the search field owns it), hover in the region cursor callback (`art->event_cursor` is set on the chat/bubble main regions so it fires per mouse-move) — both modal while open.

"New Chat" (`MIXIE_CHAT_OT_new_session`) is **non-destructive**: before clearing `scene.mixie_chat_messages` it archives the conversation to a sidecar store — deliberately *outside* the .blend/.mixar file, so project files stay lean, history survives unsaved files, and shared files never leak conversations:

```
~/.mixar/chat_history/<session_id>.json   full transcript (serializer dicts) + metadata
~/.mixar/chat_history/index.json          metadata index (self-heals by rescanning)
~/.mixar/chat_media/<session_id>/         copies of referenced local images
```

Key mechanics:

- **Upsert by session_id** — `archive_current(scene)` also runs at every turn end (`queue_processor._handle_agent_complete_internal`, IDLE branch), so history is crash-safe. `created_at` is preserved across upserts; oldest sessions beyond `MAX_ARCHIVED_SESSIONS` are pruned (records + media).
- **Sanitize on archive** — mirrors abort semantics on the snapshot dicts: loader-only bubbles dropped, `*Stopped*` marker on interrupted content, stale `action_items`/`input_type` stripped, RUNNING steps settled, live thinking collapsed.
- **Media copy** — chat images/screenshots live in Blender's per-session temp dir and die on restart; archive copies referenced local files into `chat_media/` and rewrites paths (capped by `CHAT_HISTORY_MEDIA_MAX_BYTES`; http(s) URLs untouched).
- **Reopen** (`MIXIE_CHAT_OT_open_history_session`) — tears down any in-flight turn (same cleanup as New Chat), archives the outgoing chat, restores the transcript via `restore_propgroup`, and sets `scene.mixie_session_id` back. The **backend resumes the conversation from its LangGraph checkpoint** keyed by that id (`thread_id == session_id`) — the transcript itself is never uploaded. Checkpoints are retained `CHECKPOINT_RETENTION_DAYS` (7) server-side; after expiry a reopened chat still shows its transcript but the agent starts contextually fresh.
- **Account scoping** — records store `user_email` (`scene.mixie_chat_user_id`); the popover filters to the logged-in account, and the backend independently enforces checkpoint ownership on resume.

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

- `load_pre` — flush all agent stream handlers (`cleanup_all_turn_handlers`), stop the main-thread executor (`cleanup`), clear pending responses, force-OFFLINE all scenes and close their runs (a scene whose turn is IDLE but whose run is open is aborted too). **K6 fix** wraps each step in `try/except` so a partial failure (a stale agent stream handler that refuses to close, etc.) doesn't strand later cleanup steps.
- `load_post` — re-init session state for the newly-loaded scenes (chat messages persisted as scene properties are still there).

## Cross-channel contracts (the invariants)

These are the contracts between the two repos. Breaking any of them on either side causes a class of failures:

- **`__RESULT__` protocol** — all `bpy` scripts that need to return data MUST `print("__RESULT__" + json.dumps(result))`. Plugin executor captures stdout and parses lines beginning with this prefix. Bare expressions at the end of the script are discarded.
- **`mixie_session_id` per scene** — backend addresses scripts to a specific session; plugin routes execution to the matching scene by this property. The non-pinned `agent:<connection>`/empty session runs against the user's active scene; any other unresolved per-scene session is **rejected** (see "Per-scene hard-fail" above), never silently misrouted.
- **Slot event shape** — `loader` / `content` / `ephemeral` / `todo` / `actions` / `images` / `input_type` / `interrupt_context`. Choice contexts may set `include_cancel=false` when their explicit actions are exhaustive (export preflight uses exactly Fix and Export, Export Anyways, Stop). `file_save` context is restricted to format, scope, extension, and sanitized suggested filename. Preflight reports and decisions never carry a path; the chosen path is held only in `core/export_destination.py` and never enters an agent stream or HTTP payload.
- **Tool-call pairing invariant** — every `tool_use` the backend emits must get a matching `tool_result`. B5 (RPC timeout), B6 (disconnect buffer), B8 (queue full), B-Mira (invariant guard), B1 (compaction scrub) all defend this from a different angle.
- **JWT shared across both channels** — same token, refreshed in lock-step via `refresh_access_token_shared` (K5).
- **Generation callbacks (`generation.agent_result`)** — the client owns generation submission, download and import, so it reports terminal outcomes through an acknowledged JSON-RPC request using the same method and params as the notification API. `common/job_queue/core/agent_results.py` retains callback params independently of the visible queue until the backend returns `received: true` (a `relay_failed` result retries), permanently refuses the request, or the 20-attempt/one-hour retention budget expires. Give-up logs once and prevents reinsertion without marking the result acknowledged. Queue acceptance alone never sets `Job._agent_reported`. Timed retries and the post-handshake sweep preserve the generation identity, which the backend deduplicates. The retry timer survives file loads; socket response callbacks only enqueue Python data for the main-thread sweep. This is process-local recovery, not persistence across app restarts. Retopology claims the WindowManager ref once for its per-mesh fan-out: all accepted siblings share it, and one combined outcome waits for all of them to finish. Outside that scoped batch, the enqueue script's WindowManager ref is consumed even on duplicate rejection, and the shared GUI/headless execution pump clears any unclaimed ref at the script boundary. Frozen params: `agent_ref`, `generation_id`, `feature_key`, `job_type`, `model`, `label`, `backend_job_id`, `status`, `error`, `result_names`; local paths are excluded.
- **`request_id` uniqueness** — within a connection lifetime. Plugin's `_pending_responses` and backend's tool-call tracking both key on it.

## Where to look for what

| Question | First file to read |
|----------|---------------------|
| Why did a tool call hang forever? | `main_thread_executor.py` (queue, render guard, B3/B6) |
| Why is the bubble showing stale content? | `slot_processor.py` (slot apply) + `markdown_parser.py` |
| Why did Blender just segfault? | render guard in `main_thread_executor.py`, or sandbox bypass in `executor.py` |
| Why did the agent stop responding mid-turn? | `turn_events.py` / `socket_connection.py` (replay availability, connection state) |
| Why am I getting auth errors on long sessions? | `jsonrpc_auth.py` K5 shared refresh; check both channels hold the same token |
| Why did the chat disappear after undo? | `undo_guard.py` snapshot/restore + K4 try/finally |
| Why did loading a new `.blend` break the agent? | `file_handlers.py` load_pre cleanup + K6 exception-safety |
| Why is the plugin using 15% CPU at idle? | `animation_manager.py` + `queue_processor.py` K2 scene iteration |
| Why didn't my script run? | First check sandbox in `executor.py` + `sandbox_validator.py`; then check session state in `session.py`; then check the render guard. |
| Why is the '@' mention dropdown missing/stale/mis-clicking? | `core/mention_registry.py` (candidates + ranking) and `ui/properties/mention_props.py` (query callback); interaction/geometry live C++-side in `editors/space_mixie_chat/mixie_chat_mention.cc` + the textedit hooks in `editors/interface/interface_handlers.cc` |

## Companion docs

- Backend-side companion (graph, agents, middleware, transport): `modules/agent/ARCHITECTURE.md` in the private `mixar-backend` repository.
- Fix rationale for the May 2026 audit and the deferred items / verified false positives: `docs/reviews/AGENT_STUCK_INVESTIGATION.md` and `docs/reviews/AGENT_REVIEW_2026_05_BACKLOG.md` in the private `mixar-backend` repository.

## Turn checkpoints (`core/turn_checkpoints.py`, `ui/operators/checkpoint_ops.py`)

Modules: `core/turn_checkpoints.py` (policy: capture, the jump, caps, the
public names), `core/checkpoint_store.py` (paths, index, per-kind prune),
`core/checkpoint_timeline.py` (position math, undo stamp, document helpers),
`core/checkpoint_backend.py` (bookmarks and rewinds on a worker thread),
`core/checkpoint_budget.py` (retiring session directories);
`ui/properties/history_props.py` (the card's WindowManager mirror) and
`ui/operators/checkpoint_ops.py` (card sync, the revert operator).

Before every fresh turn `chat_ops.send_message` captures the whole document with
`save_as_mainfile(copy=True)` to `~/.mixar/checkpoints/<session>/<id>.mixar`
as the `turn` record "before turn N" (sha256-deduplicated files, newest 20 per
session) and binds the record to the turn's command id once the send is
accepted. A document with Automatically Pack Resources on reports an error per
image missing on disk while packing; Blender still writes the copy, so the
capture keeps a snapshot that exists after such a `RuntimeError` and only
gives up when nothing was written. The Agent Bubble's `save_pre` purge closes the island for this save
like any other (bubble screens must never reach a file, and a later restore's
read must never find a live bubble window to free); the island is re-shown
after the save. A send started from a bubble click therefore closes the window
whose region is on the click handler's stack, which is why native click
dispatchers call operators only through `mixie_chat_call_operator_and_redraw`:
it re-checks that the region still exists in a live screen before redrawing it
(the purge restores a live context window, so only a screen walk can tell).

**One timeline, position = chat length.** The snapshot before turn N holds N-1
user messages, so `timeline(session_id, scene)` splits the turns by the scene's
user-message count: turns at or below it are *applied*, above it *reverted*.
Nothing is stored to know where the scene is, so a restart or a reopened file
cannot disagree with the card. Reverting turn N (`restore`) reads the "before
turn N" snapshot and takes every later turn with it; reapplying a reverted turn
N reads the state after N, which is the "before turn N+1" snapshot or, for the
last turn, the `tip` record. A row therefore alternates between the two lists
and never mints a copy of a stored state. Only what a jump would lose is
captured first (`_keep_leaving_state`): the `tip` when leaving the end of the
line (replaced when the tip changed), and hand edits made on a reverted
position as a `safety` record ("your edits after turn K", own cap
`MAX_SAFETY_PER_SESSION`). "Changed since the jump" is answered by Blender's
undo stack: the native `mixie_chat.undo_stamp` operator writes a fingerprint
(step count, active step) to `WindowManager.mixie_chat_undo_stamp`, taken right
after each read (`_note_arrival`) and compared on the next jump. A file read
resets the stack; interactive operators, UI property edits and scripts that
push a step move it; the chat's own property writes and the re-title do not.
Limits, accepted: a script writing `bpy.data` directly on a reverted position
is invisible (its edits are lost on the next jump), and a UI edit of a
scene-owned chat property counts as a change (one spare snapshot, within the
caps). Depsgraph traffic and file hashes are never consulted: a layout change
(the island expanding, an area changing type) flushes every ID, and a re-saved
.blend is never byte-identical. Turn numbers are the user-message count at
capture plus one, so a reply or interjection that adds a user bubble without
a snapshot leaves a gap; `_state_after` uses the next stored turn and the
prompts name stored turns only. A message sent from a reverted position drops
the reverted turns, the tip and any safety copy from that dead line (`capture`
with `kind="turn"`); a replaced line is not kept, by decision. Reverting to
before turn 1 predates the backend conversation (`session_was_new`, or a
rewind answered `has_conversation: false`): the chat's session id is cleared
for the next message, and `Scene.mixie_checkpoint_session_id` remembers the
directory so the card (`checkpoint_session_id`) still lists the timeline and
the turns can be reapplied; a new message from there mints a new session and
forgets it. A jump whose keep-capture fails is refused ("nothing was
changed"); a jump whose read fails drops the record it had just captured.
Every read is preceded by the Agent Bubble purge
(`close_restored_agent_bubble_windows`), because a jump with nothing to keep
saves nothing and `save_pre` would not have closed the island.

**Card.** The header (and the island's history-button row) shows a
Checkpoints button once the session has one. It opens the native past-chats
card in CHECKPOINTS mode (`checkpoint_ops.sync_checkpoint_entries` fills
`WindowManager.mixie_chat_history_entries`, sets `mixie_chat_history_mode`,
and passes the `can_restore` lock and its reason as
`mixie_chat_history_locked` / `mixie_chat_history_notice`): no search, the
sections "Turns" (applied, newest first), "Reverted turns" and "Safety
copies", rows read "Turn N · label" / "Safety copy · your edits after turn K",
a footer explaining the model, dimmed rows and no hand cursor while locked. A
row arms on the first click and acts on the second; the armed prompt is
computed per row by Python (`checkpoint_row_action` → entry `action`):
"Revert this turn?", "Revert turns 3–5?", "Reapply this turn?", "Reapply
turns 2–4?", "Bring back?". No modal dialog: the second click is the
confirmation, and the operator runs in EXEC only. QA targets: `chat_checkpoint_row`
(`value` = checkpoint id, `sel` = armed, `detail` = section name) and
`chat_checkpoints_close`; the chats mode exports `chat_history_row` /
`chat_history_close` the same way.

**Restore mechanics.** Only while the session is IDLE with no open run. The
snapshot is read with `wm.recover_auto_save`, then the native
`mixie_chat.retitle_document` operator gives the document its recorded
original path back in memory and marks it modified. Restore never writes the
artist's project: a titled project is dirty on its own path until they save,
an untitled one stays untitled so Ctrl-S opens Save As. Snapshots are written
with `relative_remap=False` so relative paths keep resolving against the
project folder. Recovery must return `FINISHED`: a cancelled read reports
failure without saving the document or rewinding the backend conversation.
`load_pre` skips its session abort while `turn_checkpoints.is_restoring()`,
and `turn_events.drop_scene` fences the session so the reconnect-time recovery
check does not replay the undone turns into the restored chat (the next send
lifts the fence). The checkpoint is bound to the turn through
`TurnTransport.last_command_id`, not the user bubble's `bubble_id` (a
collection reference taken before the placeholder bubble is added can go
stale). The backend is told on a worker thread — `checkpoint.mark` for a new
tip or safety record, then `checkpoint.rewind` to the record the scene landed
on — and `composer_send.can_send` refuses while that is in flight. On the 5.2
Zen layout the chat is the native island; its C++ card header draws a third
disc (arrow glyph, `AGENT_HDR_BTN3_CX`, `space_agent_bubble.cc`) that runs
`mixie_chat.show_checkpoints`. The operator defers the jump to a timer when it
is invoked from that temporary window, and the file read (and any keep
capture) runs under a `temp_override` of the main window. Contract: mixar-backend
`docs/api/frontend/turn-checkpoints.md`.
