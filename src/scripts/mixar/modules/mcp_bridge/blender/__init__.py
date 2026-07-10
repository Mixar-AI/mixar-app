# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vendored AnkleBreaker Blender MCP handler surface, adapted for Mixar.

Mixar is a Blender 5.0 fork, so the Blender MCP's handler package (scene,
object, mesh, material, modifier, render, animation, file, collection,
export/import, plus the full advanced set: modeling, uv, sculpt, armature,
curve, light, camera, texture, particle, physics, constraint, node, grease
pencil, text, lattice, vertex group, addon, analysis, viewport, validation,
recipes) runs unchanged here.

The ONLY adaptation is `utils/queue.py`: instead of the standalone plugin's
own command-queue + 50ms timer, `enqueue_command` routes handlers through
Mixar's existing `mcp_bridge.core.executor_bridge.run_on_main_thread_sync`,
so every bpy call is serialized with `mixar_execute_script` on the one
main-thread path and there is no always-on idle timer.

Entry point: `from mixar.modules.mcp_bridge.blender.handlers import route_request`
then `route_request("/api/{category}/{action}", params)`.
"""
