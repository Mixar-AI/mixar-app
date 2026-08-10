# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Register the splat render-camera handlers (see core/splat_render_camera).

Thin auto-discovered bridge: the logic lives in
``moodboard/core/splat_render_camera.py``; this module only owns handler
registration so bootstrap loads it in the UI phase.
"""

import bpy

from mixar.modules.moodboard.core import splat_render_camera as src


_HANDLERS = (
    ("load_post", src.on_load_post),
    ("render_init", src.on_render_init),
    ("render_pre", src.on_render_pre),
    ("render_complete", src.on_render_done),
    ("render_cancel", src.on_render_done),
    ("frame_change_pre", src.on_frame_change_pre),
)


def register():
    for name, fn in _HANDLERS:
        handler_list = getattr(bpy.app.handlers, name)
        if fn not in handler_list:
            handler_list.append(fn)
    # The file may already be open when this registers (script reload).
    src.on_load_post()


def unregister():
    for name, fn in _HANDLERS:
        handler_list = getattr(bpy.app.handlers, name)
        if fn in handler_list:
            handler_list.remove(fn)
