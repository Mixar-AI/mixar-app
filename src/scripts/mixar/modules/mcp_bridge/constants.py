# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the MCP bridge module.

The MCP bridge exposes Mixar's local agent-execution surface (the same
sandboxed ScriptExecutor the hosted Mixie agent drives over WebSocket) to a
local MCP server over a loopback HTTP API. This lets any MCP client (Claude
Code, Claude Desktop, ...) replace the hosted agent orchestrator entirely.
"""

# ── HTTP server ──────────────────────────────────────────────────────────────
# Loopback only. 9877 avoids the AnkleBreaker Blender MCP default (9876) so a
# stock Blender and a Mixar instance can both run bridges side by side.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877

# Environment overrides (read at register time).
ENV_ENABLED = "MIXAR_MCP_ENABLED"  # "0"/"false" disables the bridge
ENV_HOST = "MIXAR_MCP_HOST"
ENV_PORT = "MIXAR_MCP_PORT"
# Shared secret. Every POST must carry it in the X-Mixar-MCP-Token header.
# If unset, the server AUTO-GENERATES one at startup and writes it to the
# token file below (Jupyter-style), so the bridge is never unauthenticated —
# a local web page cannot forge the header (it is not a CORS-safelisted one,
# so cross-origin requests trigger a preflight the server never answers).
ENV_TOKEN = "MIXAR_MCP_TOKEN"

TOKEN_HEADER = "X-Mixar-MCP-Token"

# Where the auto-generated token is written for the local MCP server to read.
# Lives under Blender's user config dir (resolved lazily to avoid importing
# bpy at module import time).
TOKEN_FILE_NAME = "mcp_bridge_token"

# Hosts we will bind to / accept. Anything else is refused: the bridge is a
# local-control surface only and must never be network-reachable.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# Base64 GLB/PNG payloads for generation jobs can be large.
MAX_REQUEST_BODY_BYTES = 64 * 1024 * 1024  # 64 MB

# Per-request socket timeout (slow-loris guard) and concurrency cap.
SOCKET_TIMEOUT_S = 30.0
MAX_CONCURRENT_REQUESTS = 16

# ── Script execution ─────────────────────────────────────────────────────────
# The bridge marshals scripts onto Blender's main thread and waits for the
# sandboxed executor to finish. Long modeling scripts are legitimate, so the
# ceiling is generous; the default matches typical agent tool budgets.
EXECUTE_TIMEOUT_DEFAULT_S = 60.0
EXECUTE_TIMEOUT_MAX_S = 600.0

# ── Local tool domains ───────────────────────────────────────────────────────
# Read-only client-side tool registries the hosted agent already consumes.
TOOL_DOMAIN_SCENE_GRAPH = "scene_graph"
TOOL_DOMAIN_OPERATION_HISTORY = "operation_history"
TOOL_DOMAINS = (TOOL_DOMAIN_SCENE_GRAPH, TOOL_DOMAIN_OPERATION_HISTORY)
