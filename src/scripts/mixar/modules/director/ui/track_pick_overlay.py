# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hover feedback while the tracking eyedropper is live.

The eyedropper used to be a cursor and nothing else: the director clicked and
found out afterwards what had been picked, and a miss was indistinguishable
from a hit on the wrong object. While it runs, the object under the cursor is
outlined in the viewport and named beside the pointer.

Two handlers because they draw in two spaces — the outline is world geometry
(`POST_VIEW`), the label is screen text (`POST_PIXEL`). Both are scoped to the
region the modal started in: a second viewport must not paint a hover the user
is not making there.

The handles are module-level, so a modal that
never reaches its exit — a file load ending it, an exception — cannot strand a
handler with nothing able to reach it.
"""

from __future__ import annotations

import bpy

#: What the modal last saw under the cursor, read by the draw callbacks.
_hover: dict = {"object": None, "mouse": (0, 0), "region": None}

_view_handle = None
_pixel_handle = None

_OUTLINE_COLOR = (0.25, 0.92, 0.52, 0.9)
_LABEL_COLOR = (1.0, 1.0, 1.0, 1.0)
_LABEL_BACKDROP = (0.04, 0.05, 0.05, 0.85)
_LABEL_SIZE = 12
_LABEL_PAD = 6

# Blender's `Object.bound_box` corner order; these pairs are its 12 edges.
_BOX_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)


def set_hover(obj, mouse) -> bool:
    """Record what is under the cursor. True when it changed (redraw needed)."""
    changed = _hover["object"] is not obj
    _hover["object"] = obj
    _hover["mouse"] = mouse
    return changed


def _region_matches() -> bool:
    region = getattr(bpy.context, "region", None)
    return region is not None and region.as_pointer() == _hover["region"]


def _draw_outline():
    obj = _hover["object"]
    if obj is None or not _region_matches():
        return
    # Imported inside the callback, as every other Director GPU draw does:
    # the module is auto-discovered at startup and must not need a GPU
    # context, or the standalone suite's stubs, merely to be imported.
    import gpu
    import mathutils
    from gpu_extras.batch import batch_for_shader

    try:
        corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    except (AttributeError, ReferenceError, TypeError):
        return
    if len(corners) < 8:
        return
    points = []
    for start, end in _BOX_EDGES:
        points.append(corners[start])
        points.append(corners[end])

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2.0)
    # Bind before pushing a uniform, or the box draws in whatever colour the
    # previous shader left behind.
    shader.bind()
    shader.uniform_float("color", _OUTLINE_COLOR)
    batch_for_shader(shader, 'LINES', {"pos": points}).draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _draw_label():
    obj = _hover["object"]
    if obj is None or not _region_matches():
        return
    try:
        name = obj.name
    except ReferenceError:
        return
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader

    x, y = _hover["mouse"]
    font = 0
    blf.size(font, _LABEL_SIZE)
    width, height = blf.dimensions(font, name)
    # Beside the cursor, never under it: the pointer is the aim.
    left = x + 18
    bottom = y - height * 0.5

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", _LABEL_BACKDROP)
    backdrop = (
        (left - _LABEL_PAD, bottom - _LABEL_PAD),
        (left + width + _LABEL_PAD, bottom - _LABEL_PAD),
        (left + width + _LABEL_PAD, bottom + height + _LABEL_PAD),
        (left - _LABEL_PAD, bottom + height + _LABEL_PAD),
    )
    batch_for_shader(
        shader, 'TRIS', {"pos": backdrop}, indices=((0, 1, 2), (0, 2, 3))
    ).draw(shader)
    gpu.state.blend_set('NONE')

    blf.color(font, *_LABEL_COLOR)
    blf.position(font, left, bottom, 0.0)
    blf.draw(font, name)


def enable(region) -> None:
    """Start drawing the hover for *region*. Safe to call repeatedly."""
    global _view_handle, _pixel_handle
    disable()
    _hover["region"] = region.as_pointer()
    _hover["object"] = None
    _view_handle = bpy.types.SpaceView3D.draw_handler_add(
        _draw_outline, (), 'WINDOW', 'POST_VIEW',
    )
    _pixel_handle = bpy.types.SpaceView3D.draw_handler_add(
        _draw_label, (), 'WINDOW', 'POST_PIXEL',
    )


def disable() -> None:
    """Drop the handlers if any are installed. Safe to call any number of times."""
    global _view_handle, _pixel_handle
    for handle in (_view_handle, _pixel_handle):
        if handle is None:
            continue
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
        except (ValueError, ReferenceError, RuntimeError):
            pass  # already gone with its space type
    _view_handle = None
    _pixel_handle = None
    _hover.update({"object": None, "mouse": (0, 0), "region": None})
