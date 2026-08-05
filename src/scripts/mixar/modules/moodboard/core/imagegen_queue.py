# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared queue listener for Moodboard Image Gen submissions."""

_imagegen_listener = None


def get_imagegen_listener():
    """Return the cached listener used by every Moodboard Image Gen flow."""
    global _imagegen_listener
    if _imagegen_listener is not None:
        return _imagegen_listener

    import bpy

    from mixar.modules.common.job_queue.core.helpers import (
        create_scene_flag_listener,
    )

    def _on_start(scene):
        try:
            scene.mixie_imagegen_error = ""
        except (AttributeError, TypeError):
            pass

    def _on_finish(_scene):
        try:
            for area in bpy.context.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
        except Exception:
            pass

    _imagegen_listener = create_scene_flag_listener(
        "mixie_imagegen_is_generating",
        on_start=_on_start,
        on_finish=_on_finish,
    )
    return _imagegen_listener
