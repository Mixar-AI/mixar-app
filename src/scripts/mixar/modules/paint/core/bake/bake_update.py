# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.constants import TEMP_UV


def update_subdiv_global_dicing(self, context):
    """Update the Cycles subdivision dicing rate for both render and preview.

    This callback function synchronizes the Cycles render engine's dicing rate
    settings with the subdivision global dicing value from the height channel.
    It updates both the final render dicing rate and the preview dicing rate
    to maintain consistency.

    Args:
        self: The height channel property group containing the subdiv_global_dicing value.
        context: The Blender context object containing the current scene and settings.

    Returns:
        None
    """
    scene = context.scene
    height_ch = self

    scene.cycles.dicing_rate = height_ch.subdiv_global_dicing
    scene.cycles.preview_dicing_rate = height_ch.subdiv_global_dicing


def update_channel_main_uv(self, context):
    """Update and validate the main UV channel for this channel.

    This callback function ensures that the channel has a valid main UV map assigned.
    If the current main_uv is set to TEMP_UV or is empty, and there are available
    UV maps in the MPaint data, it automatically assigns the first available UV map.
    For normal map channels with smooth bump enabled, it triggers a refresh by
    reassigning the enable_smooth_bump property to itself.

    Args:
        self: The channel property group containing main_uv, type, and enable_smooth_bump properties.
        context: The Blender context object (not currently used in the function body).

    Returns:
        None
    """
    mp = self.id_data.mp

    if self.main_uv in {TEMP_UV, ""} and len(mp.uvs) > 0:
        for uv in mp.uvs:
            self.main_uv = uv.name
            break

    if self.type == "NORMAL" and self.enable_smooth_bump:
        self.enable_smooth_bump = self.enable_smooth_bump
