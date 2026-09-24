# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Placing an asset-picker tile dropped into the 3D viewport.

The island's picker (``core/asset_picker.py``) lets a tile be dragged, like a
Library tile, into a 3D viewport. The native drop (C++
``mixie_chat_asset_picker_drop.cc``) forwards the pick's action value and the
region-relative drop point here. This operator appends the asset where it
landed — on the surface under the cursor, else on the ground plane, else at
the 3D cursor's depth — and then ANSWERS the agent's pending question with a
typed reply saying the user placed it themselves, so the agent uses it as it
is instead of appending a second copy.
"""

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import asset_picker

logger = get_logger(__name__)


def _drop_location(context, x, y):
    """World point under region pixel (x, y): the first surface hit, else the
    ground plane, else the 3D cursor's depth. None means "use the cursor"."""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    try:
        from bpy_extras import view3d_utils
        from mathutils import Vector

        coord = (x, y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        depsgraph = context.evaluated_depsgraph_get()
        hit, location, *_rest = context.scene.ray_cast(depsgraph, origin, direction)
        if hit:
            return location
        ground = asset_picker.ground_point(tuple(origin), tuple(direction))
        if ground is not None:
            return Vector(ground)
        return view3d_utils.region_2d_to_location_3d(
            region, rv3d, coord, context.scene.cursor.location)
    except Exception:  # noqa: BLE001 — a projection failure still places the asset
        logger.debug("asset pick drop: could not project the drop point", exc_info=True)
        return None


class MIXIE_CHAT_OT_place_asset_pick(Operator):
    """Place a library asset dragged from the agent's picker where it was dropped"""

    bl_idname = "mixie_chat.place_asset_pick"
    bl_label = "Place Library Pick"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    value: StringProperty(name="Pick", default="", options={'HIDDEN', 'SKIP_SAVE'})
    mouse_x: IntProperty(name="X", default=-1, options={'HIDDEN', 'SKIP_SAVE'})
    mouse_y: IntProperty(name="Y", default=-1, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        live = asset_picker.live_asset_picker(scene)
        pick = None
        if live is not None:
            pick = next((p for p in live.picks if p.value == self.value), None)
        if pick is None:
            self.report({'WARNING'}, "That library pick is no longer offered")
            return {'CANCELLED'}

        from ...core import library_browse

        location = None
        if self.mouse_x >= 0 and self.mouse_y >= 0:
            location = _drop_location(context, self.mouse_x, self.mouse_y)
        ok, message = library_browse.add_asset_to_scene(
            context, pick.library, pick.blend_file, pick.asset_name, pick.asset_type,
            location=location,
        )
        if not ok:
            self.report({'WARNING'}, message)
            return {'CANCELLED'}

        # The detail column follows the placed pick.
        try:
            setattr(context.window_manager, asset_picker.SELECTED_PROP, pick.value)
        except Exception:  # noqa: BLE001 — UI state must never fail the placement
            pass

        # Answer the question: a typed reply, so the agent knows the asset is
        # already in the scene and does not append it again.
        answered = False
        try:
            result = bpy.ops.mixie_chat.send_message(
                message_override=asset_picker.drop_reply(pick))
            answered = 'FINISHED' in result
        except Exception:  # noqa: BLE001 — the placement stands on its own
            logger.debug("asset pick drop: could not answer the agent", exc_info=True)
        if answered:
            self.report({'INFO'}, f"Placed '{pick.asset_name}' and told the agent")
        else:
            self.report({'INFO'},
                        f"Placed '{pick.asset_name}' — the agent's question is still open")
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_place_asset_pick,
)
