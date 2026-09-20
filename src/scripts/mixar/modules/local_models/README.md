<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

<!--
SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited

SPDX-License-Identifier: GPL-3.0-or-later
-->

# local_models — zero-setup local LLM support

Runs the Mixar agent against a model on the user's own machine instead of a
cloud provider. The module downloads a pinned **llama.cpp `llama-server`**
build and a curated **GGUF model**, supervises the server process on
`127.0.0.1`, and executes the backend's `llm.request` relay calls against it.
It can also detect servers the user already runs (Ollama, LM Studio, oMLX,
stock llama.cpp).

## Layout

```
local_models/
├── constants.py          # pinned catalogs (tag/sha256/sizes), ports, caps
├── core/
│   ├── paths.py          # app-data dirs (main-thread resolved, cached)
│   ├── platform_info.py  # (os, arch) keys + total-RAM probe
│   ├── download.py       # verified resumable downloader (no bpy)
│   ├── archive.py        # safe tar.gz/zip extraction + layout normalize
│   ├── manifest.py       # atomic JSON install/state manifest
│   ├── catalog.py        # model list + RAM-fit ladder + recommendation
│   ├── runtime.py        # ensure_runtime / ensure_model (blocking)
│   ├── server_supervisor.py  # llama-server Popen lifecycle + health
│   ├── relay.py          # backend llm.request executor (no bpy)
│   ├── detect.py         # probe known local OpenAI-compatible servers
│   ├── download_flow.py  # download worker + 0.5s pump + sticky toast
│   └── orchestrator.py   # façade: server-state marshalling, fallback/
│                         #   restart/re-register, lifecycle; re-exports
│                         #   the download_flow API
└── ui/
    ├── properties/local_models_props.py  # WM mirror props (transient)
    └── operators/local_models_ops.py     # mixar_local.download_model /
                                          #   cancel_download / start_server /
                                          #   stop_server / remove_model
```

## How the user reaches it

The **BYOK dialog** (profile menu → AI Provider Settings) offers a
"Local (this computer)" provider (`modules/byok`): managed mode picks a
curated model (RAM-fit + downloaded state in the dropdown), Download →
Start → Save; custom mode points Mixar at a server the user already runs
(a Detected-local-apps dropdown is populated by `detect.py` off-thread).
Save registers `{provider: "local", model, api_key, base_url,
supports_vision}` via the ordinary `PUT /agent/byok`; the backend then
sends `llm.request` JSON-RPC calls down the agent WebSocket, which
`space_mixie_chat/core/connection_manager.py` relays through
`core/relay.py` on a `MixarLocalLLMRelay` daemon thread (deferred
response via `queue_response`). The client advertises the `local_llm`
handshake capability.

## Lifecycle

`bootstrap/local_models_module.py` resolves storage paths at register
time, and ~6 s after startup restores the relay's approved bases and
restarts the managed server when the saved credential is local+managed;
a 30 s health watch auto-restarts a crashed managed server (supervisor
budget: 2) and a port change re-registers the credential silently.
Shutdown paths (`unregister`, `bootstrap/shutdown_hooks` atexit) call
`server_supervisor.stop_all()`. Logout stops the server and wipes
transient UI state; downloaded files stay.

## Quick tour (Stage-2 integration surface)

```python
from mixar.modules.local_models.core import (
    paths, catalog, runtime, server_supervisor, relay, detect, manifest,
)

paths.initialize()                     # register(): main thread, once
rows = catalog.list_models()           # entries + downloaded/fit/recommended

# On a worker thread (all blocking; progress/cancel callbacks run there):
binary = runtime.ensure_runtime(progress_cb, cancel_cb)
files = runtime.ensure_model("qwen3.5-4b", progress_cb, cancel_cb)

# Non-blocking; on_state fires FROM A WORKER THREAD — marshal to main:
server_supervisor.start_server("qwen3.5-4b", on_state)
relay.set_approved_bases([server_supervisor.current()["base_url"]])

# WebSocket handler for the backend's llm.request (worker thread):
relay.handle_llm_request(params, respond)

server_supervisor.stop_all()           # unregister() + shutdown hooks
```

## Testing

```bash
python3 -m pytest -q tests/local_models
```

Standalone suite (bpy is a MagicMock); no network, no processes spawned.

## Key policies

- **Everything is pinned.** Runtime: llama.cpp tag + per-asset SHA-256 +
  byte size. Models: exact HF file + LFS SHA-256 + size. A download that
  fails verification is discarded — never executed or loaded.
- **Downloads resume.** Multi-GB GGUFs stream to `.part` files with
  `Range` resume, rolled SHA-256, total deadline scaled by size, and
  `os.replace` only after verification.
- **The managed server is private.** It binds `127.0.0.1`, requires an
  `--api-key` minted once per install, and its port lives in the manifest.
- **The relay trusts no one.** Only POST to an approved localhost/private
  base's `/v1/chat/completions`, with header allowlists and byte caps both
  ways. See ARCHITECTURE.md for the full trust model.

Storage lives under `bpy.utils.user_resource("DATAFILES")/mixar/local_models`
(`~/.mixar/local_models` fallback): `runtimes/<tag>/<variant>/`,
`models/<model_id>/`, `manifest.json`, `downloads/` (transient archives).
llama-server output goes to `<tempdir>/mixar_llama_server.log`.
