# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""scene_graph module.

A per-scene, agent-readable scene graph. Currently emits the Outliner hierarchy
(ObjectGraph): nodes = every object, edges = parent_of. Spatial / semantic
layers are added on top of the same nodes later.

The graph is built lazily (rebuilt on the next query after the scene changes)
and stored per-scene on a SKIP_SAVE Scene property. Agents traverse it via
core.tools.run_tool(scene, name, params).
"""

from .core import properties, watcher


def register():
    properties.register()
    watcher.register()


def unregister():
    watcher.unregister()
    properties.unregister()
