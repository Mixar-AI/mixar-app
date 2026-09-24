# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""One bounded focus request after a composer surface has been rebuilt."""
import time


def after_redraw(context):
    """Return to the originating editor after explicitly closing Handwriting."""
    import bpy

    if context.window is None or context.area is None or context.scene is None:
        return
    window_id = context.window.as_pointer()
    area_id = context.area.as_pointer()
    scene_id = context.scene.as_pointer()
    deadline = time.monotonic() + 1.0

    def focus():
        wm = bpy.context.window_manager
        if (time.monotonic() > deadline or wm.mixie_chat_ink_visible
                or getattr(wm, 'mixie_chat_history_visible', False)
                or getattr(wm, 'mixie_chat_rules_visible', False)):
            return None
        for window in wm.windows:
            if window.as_pointer() != window_id:
                continue
            if window.scene is None or window.scene.as_pointer() != scene_id:
                return None
            for area in window.screen.areas:
                if area.as_pointer() != area_id:
                    continue
                if area.type not in {'AGENT_BUBBLE'}:
                    return None
                if (area.type == 'AGENT_BUBBLE'
                        and getattr(wm, 'mixar_bubble_tab', 'AGENT') != 'AGENT'):
                    return None
                with bpy.context.temp_override(window=window, area=area):
                    if 'FINISHED' in bpy.ops.mixie_chat.focus_composer():
                        return None
                return 0.05
        return None

    # The native pad restores its geometry on the 100 ms maintenance tick.
    bpy.app.timers.register(focus, first_interval=0.15)
