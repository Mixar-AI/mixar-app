<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Connect an AI app to Mixar

1. Open Mixar and sign in.
2. Choose **Help → Connect AI Apps (MCP)** and pick your app. Claude Code and
   Codex have **Add to …**, which sets everything up; for other apps, **Copy**
   the shown setup and paste it where the dialog says (**Open Config File**
   opens that file). **Copy MCP Config** copies the standard `mcpServers` JSON.
3. **Setup Guide** opens the full per-app instructions.
   Tick **Let AI apps control Mixar's interface** only if the assistant should
   also see and click Mixar's interface; scene tools work without it.
4. Restart the app's MCP connection. It can start your installed Mixar when needed.

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
`mixar_scene_new` creates a tab and `mixar_scene_switch` moves to one, and every
later tool follows. Ask the assistant to create scenes with these, not a script.
`mixar_projects` and `mixar_project_open` reopen a recent project; the assistant
must ask you before saving or discarding unsaved changes.
Physical keyboard/button/wheel input interrupts queued assistant input.

Local desktop/CLI clients are supported; hosted web connectors requiring OAuth
are a separate integration.

If a call times out, inspect the scene before issuing another edit. Reuse the
reported call UUID to retrieve its recorded outcome instead of repeating an
operation with a fresh ID. Expired or ambiguous calls never automatically rerun.
Use `mixar_ui_call_status` for native UI actions and `mixar_call_status` for
backend tools. Delivery of input is separate from verifying the intended result.
