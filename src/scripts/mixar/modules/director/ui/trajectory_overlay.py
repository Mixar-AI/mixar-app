# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""World-space camera trajectory drawn over the scene while directing.

The timeline's visual language lifted into 3D: the path uses the strip's
orange, keyframes the Director green, and the playhead marker the
timeline's playhead blue — so the curve in the viewport IS the strip in
the dock. Drawn always-on-top (Flow-style) with light transparency so it
reads over any scene, and gated by ``state.show_trajectory``.
"""

import bpy

# Timeline strip orange / Director accent green / timeline playhead blue.
PATH_COLOR = (1.0, 0.72, 0.48, 0.85)
BEAT_COLOR = (0.25, 0.92, 0.52, 1.0)
PLAYHEAD_COLOR = (0.68, 0.86, 0.98, 1.0)

_handle = None
_batch_cache = {"samples": None, "path": None}


def _path_batch(samples, shader):
    """The polyline batch, rebuilt only when the cached samples change."""
    from gpu_extras.batch import batch_for_shader

    if _batch_cache["samples"] is not samples:
        _batch_cache["samples"] = samples
        _batch_cache["path"] = batch_for_shader(
            shader, 'LINE_STRIP', {"pos": samples}
        )
    return _batch_cache["path"]


def _draw():
    context = bpy.context
    scene = getattr(context, "scene", None)
    state = getattr(scene, "mixar_director", None)
    if (
        state is None
        or not state.is_directing
        or not getattr(state, "show_trajectory", False)
    ):
        return
    from ..core.shot_api import active_shot
    from ..core.trajectory import playhead_point, sample_path

    shot = active_shot(scene)
    if shot is None:
        return
    samples, beats = sample_path(shot)
    if len(samples) < 2:
        return

    import gpu
    from gpu_extras.batch import batch_for_shader

    # Always-on-top, but every state this handler changes is put back: the
    # region's remaining POST_VIEW handlers inherit whatever is left here.
    previous_depth_test = gpu.state.depth_test_get()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    line_shader.bind()
    viewport = gpu.state.viewport_get()
    line_shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
    line_shader.uniform_float("lineWidth", 2.5)
    line_shader.uniform_float("color", PATH_COLOR)
    _path_batch(samples, line_shader).draw(line_shader)

    point_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.program_point_size_set(False)
    gpu.state.point_size_set(9.0)
    point_shader.bind()
    point_shader.uniform_float("color", BEAT_COLOR)
    batch_for_shader(point_shader, 'POINTS', {"pos": beats}).draw(point_shader)

    marker = playhead_point(scene, shot)
    if marker is not None:
        gpu.state.point_size_set(12.0)
        point_shader.uniform_float("color", PLAYHEAD_COLOR)
        batch_for_shader(
            point_shader, 'POINTS', {"pos": (marker,)}
        ).draw(point_shader)

    gpu.state.point_size_set(1.0)
    gpu.state.depth_test_set(previous_depth_test)
    gpu.state.blend_set('NONE')


def register():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw, (), 'WINDOW', 'POST_VIEW'
        )


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    _batch_cache.update({"samples": None, "path": None})
