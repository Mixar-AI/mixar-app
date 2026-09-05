<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

<!--
SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited

SPDX-License-Identifier: GPL-3.0-or-later
-->

# local_models — architecture

## Big picture

```
        (UI / operators / bootstrap — orchestrator marshals to main thread)
                    │ worker threads               │ main thread timers
┌───────────────────▼───────────────────┐  ┌───────▼──────────────┐
│ runtime.ensure_runtime / ensure_model │  │ WM props / toasts /  │
│   download.py ── archive.py           │  │ panel state          │
│ server_supervisor.start_server        │  └──────────────────────┘
│   └─ health/crash watcher thread      │
│ relay.handle_llm_request              │        manifest.json
│ detect.probe_known_servers            │  (atomic, lock-guarded)
└───────────────┬───────────────────────┘
                │ 127.0.0.1:<port>, --api-key <token>
        ┌───────▼────────┐
        │  llama-server  │  (pinned llama.cpp build, subprocess)
        └────────────────┘
```

Everything under `core/` is bpy-free except `paths.py`, which touches
`bpy.utils` exactly once, on the main thread, at `initialize()` (the
generation-catalog storage pattern). All long-running work is blocking by
design and meant for daemon worker threads; Stage 2 owns marshalling
results to Blender's main thread (`bpy.app.timers`, job_queue's
`queue_download.py` pattern).

## Pinning story (supply-chain integrity)

Two artifact classes, both pinned at curation time in `constants.py`:

- **Runtime** (`llama-server`): one llama.cpp release tag
  (`LLAMA_CPP_TAG = "b10485"`). For each supported (os, arch) an ordered
  candidate list of release assets, each with its exact byte size and
  SHA-256 (values computed from the released bytes; GitHub's releases API
  exposes the same digests as `assets[].digest`). llama.cpp publishes no
  checksums file — the API digest / recorded hash IS the pin.
- **Models**: exact GGUF filenames in un-gated Hugging Face repos, pinned
  by size + SHA-256 from the HF tree API (`lfs.oid` is the LFS object's
  SHA-256). Download URLs are `resolve/main/<file>` redirects to the HF
  CDN, which supports `Range` resume.

`download.py` rolls the SHA-256 in the transfer loop (re-hashing any
resumed `.part` prefix first), so verification covers every byte on disk
and costs no second read of a 17 GB file. Only a verified transfer is
`os.replace`d to its final name; runtime archives are then extracted by
`archive.py`, which rejects traversal/absolute/escaping-link members,
normalizes the two release layouts (tar.gz nests under `llama-<tag>/`,
Windows zips are flat), re-asserts the executable bit, and strips the
macOS quarantine xattr (defensive; our urllib download does not set it —
release binaries are only ad-hoc signed, so a quarantined copy would be
Gatekeeper-blocked).

Fallback order matters: on Windows/Linux x64 the Vulkan build is
preferred and the CPU build is the fallback; `ensure_runtime` tries
candidates in order (a manifest-proven variant first) and the supervisor
reports `retry_fallback` when a build starts but never becomes healthy,
so orchestration can install the next variant and retry once.

## Manifest

`manifest.json` (atomic mkstemp+fsync+`os.replace`, module-lock guarded)
records: the proven runtime `{tag, variant_asset, ready}`, per-model
`files_ready`, `active_model_id`, the last server `port`, the `api_token`
(minted once, `secrets.token_urlsafe(24)`), and a `registered` snapshot
`{base_url, model_id, supports_vision}` of what was last announced to the
backend — Stage 2 diffs against it to know when to re-register.

## Server supervision

`server_supervisor.py` copies `bootstrap/sandbox_supervisor.py`'s
lifecycle: module `_proc` + lock; spawn kwargs `close_fds` +
`CREATE_NEW_PROCESS_GROUP` (Windows) / `start_new_session` (POSIX);
stdout+stderr to `<tempdir>/mixar_llama_server.log`; idempotent start
(live child + same model → reuse); terminate → daemon reaper (wait 5 s →
kill → wait 5 s). `stop_all()` exists for Stage 2 to wire into
`bootstrap/shutdown_hooks._run_all_cleanups` AND `unregister()` — a
llama-server holding gigabytes of RAM must never outlive Blender.

argv: `llama-server -m <gguf> --host 127.0.0.1 --port <port> --no-webui
--api-key <token> -ngl 99 -c 16384 [--mmproj <mmproj>]`. The port is the
manifest port when still free (bind-tested), else a fresh bind-tested
port from 11500–11599, persisted back.

A daemon watcher polls `GET /health` (unauthenticated by llama.cpp
design; 503 while loading, 200 when ready — budget 240 s because a first
load of a big model streams gigabytes from disk), then blocks in
`wait()` to notice crashes. **All `on_state(state, detail)` callbacks
fire from this worker thread**; states: `spawning`, `waiting_health`,
`ready`, `retry_fallback`, `failed`, `crashed`, `stopped`. Auto-restart
policy belongs to Stage 2; the supervisor only counts crashes and
exposes `restarts_exhausted()` (cap 2). A generation counter silences
stale watchers after deliberate stops/restarts.

## Relay trust model

The backend's LOCAL provider sends `llm.request` over the agent
WebSocket; `relay.handle_llm_request` executes it locally. Three layers,
none of which trusts the others blindly:

1. **The backend validates the target** it asks for (it only ever asks
   for the base the client registered).
2. **The client re-validates on its own network**: POST only; http(s)
   only; the host must be loopback / RFC1918 / IPv6 ULA — for DNS names
   *every* `getaddrinfo` answer must qualify (one public answer refuses
   the request, defeating rebind-style names), and link-local is
   deliberately excluded so `169.254.169.254` metadata endpoints are
   unreachable; the full (scheme, host, port, path) must match a
   currently **approved base** (`set_approved_bases`: the managed
   server's base from the manifest, plus at most one custom base the
   user explicitly saved), and the only path ever derived/allowed is
   `/v1/chat/completions`. The fetched URL is rebuilt from the validated
   parts (userinfo/query/fragment refused), HTTP redirects are never
   followed (a 3xx passes through as a plain non-2xx result with
   `Location` stripped by the allowlist), and DNS-name targets are
   pinned to the address that passed the allowlist so connect-time
   re-resolution cannot be rebound (https + DNS name is refused — TLS
   cannot be pinned to an IP without breaking certificate verification).
   Request/response byte caps (8 MiB each way, kept under the backend's
   16 MiB WebSocket frame limit) and header allowlists apply in both
   directions.
3. **The api token secures the localhost server from other local
   processes**: llama-server refuses requests without the `--api-key`
   token, which only the manifest (and the backend, via registration)
   knows — a random local process cannot use the model server, and the
   relay never invents credentials (the Authorization header arrives
   from the backend and is merely allowlisted through).

Success results pass the raw status through (`{"status_code", "headers",
"body"}` — non-2xx included, the backend SDK interprets provider
errors); validation/transport failures produce
`{"error": {"code", "message"}}` markers the WebSocket layer translates
into JSON-RPC errors.

## Fit ladder (catalog.py)

`fits` when `total_file_bytes * 1.15 + 2 GiB <= total RAM`; `tight` when
the files alone still fit (warn); `too_big` otherwise; `unknown` when the
RAM probe failed (0 → never crash a panel, just skip warnings).
`recommend_default()` = the largest `fits` entry, else the catalog
default (`qwen3.5-4b`). RAM probing: `os.sysconf` (Linux),
`sysctl -n hw.memsize` (macOS), `GlobalMemoryStatusEx` (Windows) — all
failure-tolerant.

## Detection of user-run servers

`detect.probe_known_servers()` GETs `/v1/models` on the default ports of
Ollama (11434), LM Studio (1234), oMLX (8000) and stock llama.cpp (8080)
at 127.0.0.1, returning kind/base_url/model-ids for responders.
Blocking and failure-silent; callers run it on a worker thread.

## Threading rules (house style)

- Background threads never touch `bpy`; `paths.initialize()` pre-resolves
  the only bpy-dependent value on the main thread.
- Progress/cancel/on_state callbacks run on the calling worker thread and
  must only read/write plain values; Stage 2 marshals via
  `bpy.app.timers.register(..., first_interval=0.0)` and the 0.5 s
  progress-mirror timer pattern from `job_queue/core/queue_download.py`.
- `manifest.py` and `relay.py` are internally lock-guarded; any thread
  may call them.

## Stage 2 wiring (UI, lifecycle, transport)

- **`core/orchestrator.py` is the façade every caller imports; it and
  `core/download_flow.py` (the download half, split out for the 500-line
  rule and re-exported) are the only threads+timers owners.**
  `start_download(model_id)` runs `ensure_runtime` + `ensure_model` on a
  `MixarLocalModelDownload` daemon; the worker writes plain ints on a
  module state object; a self-gating 0.5 s `bpy.app.timers` pump mirrors
  them into `wm.mixar_local_dl_*` and ONE sticky toast (stable id
  `LOCAL_MODEL_TOAST_ID`, enqueue_toast discipline: re-push only on text
  change, user dismissal respected, "Local model ready" / error /
  dismiss on the terminal tick). Supervisor `on_state` callbacks are
  marshalled via `bpy.app.timers.register(first_interval=0.0)`;
  `retry_fallback` installs the next runtime variant off-thread and
  retries ONCE; `crashed` auto-restarts while
  `restarts_exhausted()` is False and the manifest registration is
  managed; `ready` refreshes `relay.set_approved_bases` and re-PUTs the
  credential when the port changed.
- **UI**: `ui/properties/local_models_props.py` (transient WM mirrors,
  wiped on unregister/logout) and `ui/operators/local_models_ops.py`
  (`mixar_local.download_model/cancel_download/start_server/stop_server/
  remove_model`, all `SKIP_SAVE` ids). The user-facing form is the BYOK
  dialog's Local branch — `modules/byok/ui/operators/byok_local_ops.py`
  (draw/poll/execute + `mixar_byok.local_rescan`) over
  `modules/byok/core/local_provider.py` (item caches, detected-apps
  mirror, managed/custom save orchestration through
  `byok_client.save_credentials(base_url=…, supports_vision=…)`).
- **Transport**: `JSONRPCMethod.LLM_REQUEST` in
  `space_mixie_chat/constants.py`; `jsonrpc_client._handle_llm_request`
  mirrors execute_script's deferred contract (callback returns None →
  reply later via `queue_response`); the ConnectionManager closure spawns
  a `MixarLocalLLMRelay` daemon running `relay.handle_llm_request` — the
  WS receive thread never blocks and the worker never touches Blender
  state. The handshake advertises capability `"local_llm"`. Relay
  validation/transport failures travel as `{"error": {code, message}}`
  result payloads (the same channel execute_script failures use).
- **Lifecycle**: `bootstrap/local_models_module.py` (register:
  `paths.initialize()`; +6 s: `orchestrator.resume_registered()`; 30 s
  `watch_tick` self-heal; unregister: `orchestrator.shutdown()`), a
  `stop_all` entry in `bootstrap/shutdown_hooks._run_all_cleanups`
  (atexit mirror included), and logout
  (`auth_ops._clear_byok_state_on_logout` → `orchestrator.on_logout()`:
  stop server, clear approved bases + WM mirrors; files stay).
