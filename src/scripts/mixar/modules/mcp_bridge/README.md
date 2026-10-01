<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Connect Claude or Codex to Mixar

1. Open Mixar and sign in.
2. Choose **Help → Connect Claude / Codex** and copy the setup for your client.
   Copying setup enables MCP.
3. Add that setup to Claude Code, Claude Desktop or Codex.
4. Restart the client's MCP connection. It can start your installed Mixar when needed.

Ask the assistant to inspect the scene, make a change, and verify it with a
viewport image. Tools cover scene and geometry inspection, Blender scripting,
materials and layers, UVs, generation, assets, animation through scripting,
rendering and export. Tool discovery includes schemas and pricing policy.
The local UI tools inspect visible controls, return window images, and operate
observed controls through native clicks, keyboard input and bounded gestures.
Use a fresh observation before acting and check state and pixels afterwards.

Inspection, connection discovery and local UI input are free. Successful scene-changing tools
use Mixar's configured per-call credit rate. AI generation retains its existing
price. Every call reports usage; the external assistant's model is provided by
Claude/Codex. Use `mixar_credit_balance` to inspect your available balance.

The setup uses a stable per-user launcher backed by Mixar's bundled Python.
It requires no separate Python packages or copied account token. **Disable** in
the same dialog revokes access. If multiple opted-in Mixar processes are running,
the assistant selects one using `mixar_ui_context`. The connection pins its scene;
after deliberately changing scenes, inspect context and bind the new session.
Physical keyboard/button/wheel input interrupts queued assistant input.

This client requires an MCP-enabled Mixar backend. A 404 means that backend
deployment is still needed. Local desktop/CLI clients are supported; hosted web
connectors requiring OAuth are a separate integration.

If a call times out, inspect the scene before issuing another edit. Reuse the
reported call UUID to retrieve its recorded outcome instead of repeating an
operation with a fresh ID. Expired or ambiguous calls never automatically rerun.
Use `mixar_ui_call_status` for native UI actions and `mixar_call_status` for
backend tools. Delivery of input is separate from verifying the intended result.

The native UI integration is under development. Full platform, sculpt/paint,
physical takeover and installation-update acceptance are still required before release.
