# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Terrain Operators

Native terrain operators (mixie.terrain_*) the backend agent drives. Each is a thin
wrapper over terrain.core.terrain_core and emits a ``__RESULT__<json>`` line so the
backend's _extract_result_data picks up created objects / status in one RPC round-trip
(the mixie.imagegen_generate precedent).
"""

import json

import bpy
from bpy.props import FloatProperty, IntProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.terrain.core import hydrology, masks, scatter, terrain_core

logger = get_logger(__name__)


def _emit(result):
    print("__RESULT__" + json.dumps(result))


def _run(op, fn):
    try:
        res = fn()
    except Exception as e:  # noqa: BLE001
        logger.exception("%s failed", op.bl_idname)
        res = {"success": False, "error": "{}: {}".format(type(e).__name__, e)}
    _emit(res)
    return {"FINISHED"} if res.get("success") else {"CANCELLED"}


class MIXIE_OT_terrain_create(Operator):
    """Create a terrain grid driven by the MasterTerrain geometry-node group."""

    bl_idname = "mixie.terrain_create"
    bl_label = "Create Terrain"
    bl_options = {"REGISTER", "UNDO"}

    size: FloatProperty(default=200.0)
    resolution: IntProperty(default=256, min=2, max=1024)
    preset: StringProperty(default="mountains")
    name: StringProperty(default="Terrain")

    def execute(self, context):
        return _run(self, lambda: terrain_core.create_terrain(
            self.size, self.resolution, self.preset, self.name))


class MIXIE_OT_terrain_set_inputs(Operator):
    """Tune MasterTerrain inputs non-destructively. `inputs_json` is a JSON object."""

    bl_idname = "mixie.terrain_set_inputs"
    bl_label = "Set Terrain Inputs"
    bl_options = {"REGISTER", "UNDO"}

    object_name: StringProperty(default="Terrain")
    inputs_json: StringProperty(default="{}")

    def execute(self, context):
        return _run(self, lambda: terrain_core.set_inputs(
            self.object_name, json.loads(self.inputs_json or "{}")))


class MIXIE_OT_terrain_set_material(Operator):
    """Re-tint the TerrainMaterial zoning to a biome (alpine / verdant / desert)."""

    bl_idname = "mixie.terrain_set_material"
    bl_label = "Set Terrain Material"
    bl_options = {"REGISTER", "UNDO"}

    object_name: StringProperty(default="Terrain")
    biome: StringProperty(default="alpine")

    def execute(self, context):
        return _run(self, lambda: terrain_core.set_material(self.object_name, self.biome))


class MIXIE_OT_terrain_carve_channel(Operator):
    """Carve a graded channel / streambed along a route. Bakes the procedural terrain
    to real geometry first, so tune the base shape (set_inputs) BEFORE carving."""

    bl_idname = "mixie.terrain_carve_channel"
    bl_label = "Carve Channel"
    bl_options = {"REGISTER", "UNDO"}

    object_name: StringProperty(default="Terrain")
    route_json: StringProperty(default="[]")  # flat [x0,y0,x1,y1,...]
    width: FloatProperty(default=6.0, min=0.1)
    depth: FloatProperty(default=1.4, min=0.0)
    bank: FloatProperty(default=4.0, min=0.0)

    def execute(self, context):
        return _run(self, lambda: hydrology.carve_channel(
            self.object_name, json.loads(self.route_json or "[]"),
            self.width, self.depth, self.bank))


class MIXIE_OT_terrain_set_water(Operator):
    """Place / resize a still water plane at world Z `level`, sized to the terrain."""

    bl_idname = "mixie.terrain_set_water"
    bl_label = "Set Terrain Water"
    bl_options = {"REGISTER", "UNDO"}

    object_name: StringProperty(default="Terrain")
    level: FloatProperty(default=0.0)
    name: StringProperty(default="Water")
    margin: FloatProperty(default=2.0)

    def execute(self, context):
        return _run(self, lambda: hydrology.set_water(
            self.object_name, self.level, self.name, self.margin))


class MIXIE_OT_terrain_compute_masks(Operator):
    """Compute ecological masks (moisture / height-above-water / slope / distance-to-
    water) as point attributes the biome scatter reads. `route_json` optional (falls
    back to the carved channel route)."""

    bl_idname = "mixie.terrain_compute_masks"
    bl_label = "Compute Terrain Masks"
    bl_options = {"REGISTER", "UNDO"}

    object_name: StringProperty(default="Terrain")
    route_json: StringProperty(default="")  # flat [x0,y0,...]; empty = use stored route
    water_level: FloatProperty(default=0.0)
    moisture_radius: FloatProperty(default=14.0, min=0.1)

    def execute(self, context):
        route = json.loads(self.route_json) if self.route_json else None
        return _run(self, lambda: masks.compute_masks(
            self.object_name, route, self.water_level, self.moisture_radius))


class MIXIE_OT_terrain_scatter_biome(Operator):
    """Scatter Botaniq vegetation by ecological masks (riparian / meadow / forest).
    Requires compute_masks first. `maturity` (0..1+) scales density (succession)."""

    bl_idname = "mixie.terrain_scatter_biome"
    bl_label = "Scatter Biome"
    bl_options = {"REGISTER", "UNDO"}

    object_name: StringProperty(default="Terrain")
    biome: StringProperty(default="riparian")
    maturity: FloatProperty(default=1.0, min=0.0, max=3.0)
    botaniq_path: StringProperty(default="")  # override; empty = env/auto

    def execute(self, context):
        return _run(self, lambda: scatter.scatter_biome(
            self.object_name, self.biome, self.maturity,
            self.botaniq_path or None))


classes = (
    MIXIE_OT_terrain_create,
    MIXIE_OT_terrain_set_inputs,
    MIXIE_OT_terrain_set_material,
    MIXIE_OT_terrain_carve_channel,
    MIXIE_OT_terrain_set_water,
    MIXIE_OT_terrain_compute_masks,
    MIXIE_OT_terrain_scatter_biome,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
