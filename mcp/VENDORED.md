<!-- SPDX-FileCopyrightText: 2026 AnkleBreaker Studio -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Vendored sources

The Blender tool surface in this MCP is vendored **verbatim** from AnkleBreaker's
standalone Blender MCP, because Mixar is a Blender 5.0 fork and the bpy handlers
run unchanged. This file records where each tree came from so upstream syncs are
a deliberate, auditable step rather than a forever-manual diff.

| Vendored tree | Upstream repo | Upstream path |
|---|---|---|
| `mcp/src/blender/tools/`, `tool-tiers.js`, `validate-params.js`, `reference/loader.js` | `AnkleBreaker-Studio/blender-mcp-server` | `src/tools/`, `src/tool-tiers.js`, `src/validate-params.js`, `src/reference/loader.js` |
| `mcp/reference-data/` | `AnkleBreaker-Studio/blender-mcp-server` | `reference-data/` |
| `src/scripts/mixar/modules/mcp_bridge/blender/{handlers,utils,recipe}/` | `AnkleBreaker-Studio/blender-mcp-plugin` | `handlers/`, `utils/`, `recipe/` |

**Upstream commit at vendoring time:** record the source SHA of each repo here when
you (re)vendor. Left blank on first import — fill from `git-mcp repos get` / the
repo's default branch HEAD.

- `blender-mcp-server`: `main` @ `<sha>`
- `blender-mcp-plugin`: `main` @ `<sha>`

## Mixar adaptations (do NOT overwrite on re-sync)

These are the *only* files that diverge from upstream. A re-sync must re-apply them:

1. **`src/scripts/mixar/modules/mcp_bridge/blender/utils/queue.py`** — replaced the
   plugin's own command-queue + 50 ms timer with a shim that routes handlers
   through `core/executor_bridge.run_on_main_thread_sync` (one serialized
   main-thread path shared with `mixar_execute_script`, no idle timer).
2. **`mcp/src/blender/blender-bridge.js`** — replaced the standalone HTTP client
   with a shim over Mixar's token-authenticated `callBridge`, posting to `/api/*`;
   also enforces the raw-python-exec opt-out client-side.
3. **`mcp/src/blender/config.js`** — Mixar-specific `allowPythonExec` gate
   (`MIXAR_MCP_ALLOW_PYTHON_EXEC`).
4. **`mcp/src/blender/reference/loader.js`** — `DATA_DIR` points at `mcp/reference-data`
   (one level higher than upstream's layout).
5. **`mcp/src/blender/tools/advanced/python-exec.js`** — corrected the disabled-exec
   message to reference `MIXAR_MCP_ALLOW_PYTHON_EXEC`.

Everything else under the vendored trees is byte-for-byte upstream; verify a
re-sync with `git hash-object <file>` against the upstream blob SHA.
