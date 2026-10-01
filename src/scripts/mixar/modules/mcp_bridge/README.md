<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Connect Claude or Codex to Mixar

1. Open Mixar and sign in.
2. Choose **Help → Connect Claude / Codex → Enable MCP**.
3. Copy the setup for Claude Code, Claude Desktop or Codex and add it to that client.
4. Restart the client's MCP connection, keeping Mixar open.

Ask the assistant to inspect the scene, make a change, and verify it with a
viewport image. Tools cover scene and geometry inspection, Blender scripting,
materials and layers, UVs, generation, assets, animation through scripting,
rendering and export. Tool discovery includes schemas and pricing policy.

Inspection and connection discovery are free. Successful scene-changing tools
use Mixar's configured per-call credit rate. AI generation retains its existing
price. Every call reports usage; the external assistant's model is provided by
Claude/Codex. Use `mixar_credit_balance` to inspect your available balance.

The setup uses the Python bundled with Mixar and `scripts/mixar/mcp.py`.
It requires no separate Python packages or copied account token. **Disable** in
the same dialog revokes access. If multiple opted-in Mixar processes are running,
add `--instance <UUID>` to the launcher arguments; `--session <UUID>` pins a scene.

This client requires an MCP-enabled Mixar backend. A 404 means that backend
deployment is still needed. Local desktop/CLI clients are supported; hosted web
connectors requiring OAuth are a separate integration.

If a call times out, inspect the scene before issuing another edit. Reuse the
reported call UUID to retrieve its recorded outcome instead of repeating an
operation with a fresh ID. Expired or ambiguous calls never automatically rerun.
