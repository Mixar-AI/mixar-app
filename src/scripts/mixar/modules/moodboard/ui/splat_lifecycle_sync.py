# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Register the splat lifecycle handlers (see core/splat_lifecycle).

Thin auto-discovered bridge, mirroring ``splat_render_sync``: the logic lives
in ``moodboard/core/splat_lifecycle.py``; this module only owns handler
registration so bootstrap loads it in the UI phase.
"""

import bpy

from mixar.modules.moodboard.core import splat_lifecycle as sl


_HANDLERS = (
    ("depsgraph_update_post", sl.on_depsgraph_update),
    ("load_post", sl.on_load_post),
)


def register():
    for name, fn in _HANDLERS:
        handler_list = getattr(bpy.app.handlers, name)
        if fn not in handler_list:
            handler_list.append(fn)


def unregister():
    sl.cancel_pending()
    for name, fn in _HANDLERS:
        handler_list = getattr(bpy.app.handlers, name)
        if fn in handler_list:
            handler_list.remove(fn)
