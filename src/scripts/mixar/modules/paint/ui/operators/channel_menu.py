# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel menu for Mixar"""

import bpy

from ...core.node.node_utils import get_active_mpaint_node


class CHANNELS_MT_AddChannelMenu(bpy.types.Menu):
    """Menu with common channel presets for one-click addition"""

    bl_idname = "CHANNELS_MT_add_channel_menu"
    bl_label = "Add Channel"
    bl_description = "Add a new channel from presets"

    def draw(self, context):
        """Draw the channel presets menu.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'

        # Get existing channels to gray out already added ones
        node = get_active_mpaint_node()
        existing_channels = set()
        if node and node.node_tree:
            mp = node.node_tree.mp
            existing_channels = {ch.name for ch in mp.channels}

        # ===== RGB CHANNELS =====
        layout.label(text="Color Channels:", icon='COLOR')

        # Color/Base Color (RGB, sRGB)
        if "Color" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Color", icon='COLOR')
            op.channel_name = "Color"
            op.channel_type = "RGB"
            op.non_color = False  # sRGB
            op.enable = False
            op.connect_to_bsdf = True

        # Emission (RGB, non-color)
        # Note: set_strength_to_one enables Emission Strength on BSDF in Blender 4.0+
        if "Emission" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Emission", icon='LIGHT')
            op.channel_name = "Emission"
            op.channel_type = "RGB"
            op.non_color = False  # Emission typically uses sRGB
            op.enable = False
            op.connect_to_bsdf = True
            op.set_strength_to_one = True

        # Transmission (VALUE - connects to Transmission Weight in Blender 4.0+)
        if "Transmission" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Transmission", icon='MATFLUID')
            op.channel_name = "Transmission"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # NOTE: Subsurface Color was removed from Principled BSDF in Blender 4.0+
        # The subsurface tint now comes from Base Color itself

        layout.separator()

        # ===== VALUE CHANNELS =====
        layout.label(text="Value Channels:", icon='PLUS')

        # Metallic (VALUE, non-color)
        if "Metallic" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Metallic", icon='META_BALL')
            op.channel_name = "Metallic"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Roughness (VALUE, non-color)
        if "Roughness" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Roughness", icon='MATSHADERBALL')
            op.channel_name = "Roughness"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Subsurface (connects to Subsurface Weight - no companion needed as it IS the weight)
        if "Subsurface" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Subsurface", icon='SURFACE_NSURFACE')
            op.channel_name = "Subsurface"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Specular (connects to Specular IOR Level)
        if "Specular" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Specular", icon='SHADING_SOLID')
            op.channel_name = "Specular"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Specular Tint
        if "Specular Tint" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Specular Tint", icon='SHADING_SOLID')
            op.channel_name = "Specular Tint"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Sheen (connects to Sheen Weight - no companion needed as it IS the weight)
        if "Sheen" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Sheen", icon='MATCLOTH')
            op.channel_name = "Sheen"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Sheen Tint (RGB color, sRGB)
        # Note: set_strength_to_one enables Sheen Weight so tint is visible
        if "Sheen Tint" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Sheen Tint", icon='MATCLOTH')
            op.channel_name = "Sheen Tint"
            op.channel_type = "RGB"
            op.non_color = False
            op.enable = False
            op.connect_to_bsdf = True
            op.set_strength_to_one = True

        # Clearcoat (connects to Coat Weight - no companion needed as it IS the weight)
        if "Clearcoat" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Clearcoat", icon='MATSPHERE')
            op.channel_name = "Clearcoat"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Clearcoat Roughness
        # Note: set_strength_to_one enables Coat Weight so roughness is visible
        if "Clearcoat Roughness" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Clearcoat Roughness", icon='MATSPHERE')
            op.channel_name = "Clearcoat Roughness"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True
            op.set_strength_to_one = True

        # Coat IOR
        if "Coat IOR" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Coat IOR", icon='MATSPHERE')
            op.channel_name = "Coat IOR"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Subsurface Scale
        if "Subsurface Scale" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Subsurface Scale", icon='SURFACE_NSURFACE')
            op.channel_name = "Subsurface Scale"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Subsurface Anisotropy
        if "Subsurface Anisotropy" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Subsurface Anisotropy", icon='SURFACE_NSURFACE')
            op.channel_name = "Subsurface Anisotropy"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # IOR (Index of Refraction)
        if "IOR" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="IOR", icon='MATFLUID')
            op.channel_name = "IOR"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Anisotropic
        if "Anisotropic" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Anisotropic", icon='ORIENTATION_NORMAL')
            op.channel_name = "Anisotropic"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Anisotropic Rotation
        if "Anisotropic Rotation" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Anisotropic Rotation", icon='DRIVER_ROTATIONAL_DIFFERENCE')
            op.channel_name = "Anisotropic Rotation"
            op.channel_type = "VALUE"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Ambient Occlusion (RGB, non-color, no direct BSDF connection - multiplied with Color)
        if "Ambient Occlusion" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Ambient Occlusion", icon='SHADING_RENDERED')
            op.channel_name = "Ambient Occlusion"
            op.channel_type = "RGB"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = False  # AO is multiplied with Color, not connected directly

        layout.separator()

        # ===== NORMAL/BUMP CHANNELS =====
        layout.label(text="Surface Channels:", icon='NORMALS_FACE')

        # Normal (NORMAL type, non-color)
        if "Normal" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Normal", icon='NORMALS_FACE')
            op.channel_name = "Normal"
            op.channel_type = "NORMAL"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Bump (connects to Normal socket)
        if "Bump" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Bump", icon='SMOOTHCURVE')
            op.channel_name = "Bump"
            op.channel_type = "NORMAL"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True

        # Clearcoat Normal (connects to Coat Normal - needs Coat Weight enabled)
        if "Clearcoat Normal" not in existing_channels:
            op = layout.operator("channels.add_channel_quick", text="Clearcoat Normal", icon='NORMALS_FACE')
            op.channel_name = "Clearcoat Normal"
            op.channel_type = "NORMAL"
            op.non_color = True
            op.enable = False
            op.connect_to_bsdf = True
            op.set_strength_to_one = True

        layout.separator()

        # ===== CUSTOM CHANNEL =====
        layout.operator("channels.add_channel", text="Custom Channel...", icon='PREFERENCES')


# Classes for registration
classes = (
    CHANNELS_MT_AddChannelMenu,
)
