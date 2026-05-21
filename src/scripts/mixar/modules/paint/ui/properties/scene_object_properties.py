# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene and Object property group definitions.

This module contains the MPaintSceneProps, MPaintObjectProps, and
MPaintObjectUVHash property groups used for scene and object-level
settings in the paint system.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)


class MPaintSceneProps(bpy.types.PropertyGroup):
    """Property group for scene-level paint settings.

    Stores original color management and compositing settings.
    """

    ori_display_device: StringProperty(default="")
    ori_view_transform: StringProperty(default="")
    ori_exposure: FloatProperty(default=0.0)
    ori_gamma: FloatProperty(default=1.0)
    ori_look: StringProperty(default="")
    ori_use_curve_mapping: BoolProperty(default=False)
    ori_use_compositing: BoolProperty(default=False)
    ori_compositing_node_name: StringProperty(default="")


class MPaintObjectUVHash(bpy.types.PropertyGroup):
    """Property group for storing UV hash information per UV layer."""

    name: StringProperty(default="")
    uv_hash: StringProperty(default="")


class MPaintObjectProps(bpy.types.PropertyGroup):
    """Property group for object-level paint settings.

    Stores original modifier levels, UV offsets, mesh hashes,
    and texture paint transform data.
    """

    ori_subsurf_render_levels: IntProperty(default=1)
    ori_subsurf_levels: IntProperty(default=1)
    ori_multires_render_levels: IntProperty(default=1)
    ori_multires_levels: IntProperty(default=1)

    ori_mirror_offset_u: FloatProperty(default=0.0)
    ori_mirror_offset_v: FloatProperty(default=0.0)
    ori_offset_u: FloatProperty(default=0.0)
    ori_offset_v: FloatProperty(default=0.0)

    mesh_hash: StringProperty(default="")
    uv_hashes: CollectionProperty(type=MPaintObjectUVHash)

    texpaint_translation: FloatVectorProperty(size=3, default=(0.0, 0.0, 0.0))
    texpaint_rotation: FloatVectorProperty(size=3, default=(0.0, 0.0, 0.0))
    texpaint_scale: FloatVectorProperty(size=3, default=(1.0, 1.0, 1.0))


# Classes to be registered
classes = [
    MPaintSceneProps,
    MPaintObjectUVHash,
    MPaintObjectProps,
]
