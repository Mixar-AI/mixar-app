# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transient messages shown on the moodboard canvas.

Split out of the graph operators (500-line rule): this is scene state plus a
timer, not an operator. The C++ draw pass only ever READS the properties it
writes.
"""

# How long a refusal stays on the canvas. Long enough to read a short sentence,
# short enough that it never becomes furniture.
_NOTICE_SECONDS = 3.0


def post_graph_notice(scene, message: str, near_node_id: str = "") -> None:
    """Show `message` on the canvas, anchored on the node it concerns.

    Cleared by a one-shot timer rather than by comparing clocks in the draw
    pass: Python's `time.monotonic` and Blender's `BLI_time_now_seconds` are
    both monotonic but have different epochs, so a timestamp written by one and
    read by the other is meaningless. A timer also owns the redraw that makes
    the message disappear.
    """
    import bpy

    if scene is None:
        return
    anchor_x = float(getattr(scene, "mixie_moodboard_context_x", 0.0))
    anchor_y = float(getattr(scene, "mixie_moodboard_context_y", 0.0))
    # Prefer the node that was aimed at: that is what the message is about, and
    # the click point can be stale by the time a drag is released.
    try:
        from mixar.modules.moodboard.core.node_graph import action_node_by_id

        target = action_node_by_id(scene, near_node_id) if near_node_id else None
        if target is not None:
            anchor_x = float(target.position_x)
            anchor_y = float(target.position_y) + float(target.height)
    except Exception:
        pass

    scene.mixie_moodboard_graph_notice = message
    scene.mixie_moodboard_graph_notice_x = anchor_x
    scene.mixie_moodboard_graph_notice_y = anchor_y

    scene_name = scene.name

    def _clear():
        try:
            target_scene = bpy.data.scenes.get(scene_name)
            if target_scene is not None:
                target_scene.mixie_moodboard_graph_notice = ""
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'MIXIE':
                        area.tag_redraw()
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_clear, first_interval=_NOTICE_SECONDS)
    except Exception:
        pass
