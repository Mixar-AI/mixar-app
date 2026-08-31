# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty, PointerProperty

from ..texel import ui
from ..texel import core_td_operators
from ..texel import add_td_operators
from ..texel import viz_operators
from ..texel import props
from ..texel import preferences


classes = (
    props.TDAddonProps,
    ui.IMAGE_PT_texel_density,
    # ui.TDAddonView3DPanel,  # Disabled - only show in Mixar UV Properties
    ui.TDAddonUVPanel,
    core_td_operators.TexelDensityCheck,
    core_td_operators.TexelDensitySet,
    add_td_operators.TexelDensityCopy,
    add_td_operators.CalculatedToSet,
    add_td_operators.CalculatedToSelect,
    add_td_operators.PresetSet,
    add_td_operators.SelectByTDOrUVSpace,
    add_td_operators.OpenURL,
    add_td_operators.ShowAddonPrefs,
    viz_operators.CheckerAssign,
    viz_operators.CheckerRestore,
    viz_operators.ClearSavedMaterials,
    viz_operators.BakeTDToVC,
    viz_operators.ClearTDFromVC,
    preferences.TDAddonProperties,
    preferences.TDObjectSetting,
    preferences.ApplyDefaultsToProps,
    preferences.ResetPreferences,
)


def register():

    bpy.types.Material.is_td_material = BoolProperty(
        name="Is TD Checker Material",
        description="Custom Property for Texel Density Checker",
        default=False,
    )

    bpy.types.Image.is_td_texture = BoolProperty(
        name="Is TD Checker Texture",
        description="Custom Property for Texel Density Checker",
        default=False,
    )

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.td_settings = bpy.props.CollectionProperty(
        type=preferences.TDObjectSetting
    )
    bpy.types.Scene.td = PointerProperty(type=props.TDAddonProps)
    bpy.types.Scene.td_addon_props = PointerProperty(type=preferences.TDAddonProperties)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Image.is_td_texture
    del bpy.types.Material.is_td_material

    del bpy.types.Scene.td
    del bpy.types.Scene.td_addon_props
    del bpy.types.Object.td_settings
