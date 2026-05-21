# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Callback wrapper functions for layer properties.

These wrapper functions use delayed imports to avoid circular dependencies
during bootstrap loading. The actual implementations are in layer_ui_helpers
and layer_channel_callbacks modules.
"""


def get_normal_map_type_items(self, context):
    """Get enum items for normal map type."""
    from ..helpers.layer_ui_helpers import get_normal_map_type_items as _impl

    return _impl(self, context)


def update_blend_type(self, context):
    """Update callback for blend type changes."""
    from ..helpers.layer_ui_helpers import update_blend_type as _impl

    return _impl(self, context)


def update_channel_active_edit(self, context):
    """Update callback for channel active edit changes."""
    from ..helpers.layer_ui_helpers import update_channel_active_edit as _impl

    return _impl(self, context)


def update_channel_enable(self, context):
    """Update callback for channel enable changes."""
    from ..helpers.layer_ui_helpers import update_channel_enable as _impl

    return _impl(self, context)


def update_channel_intensity_value(self, context):
    """Update callback for channel intensity value changes."""
    from ..helpers.layer_ui_helpers import update_channel_intensity_value as _impl

    return _impl(self, context)


def update_bump_midlevel(self, context):
    """Update callback for bump midlevel changes."""
    from ..helpers.layer_ui_helpers import update_bump_midlevel as _impl

    return _impl(self, context)


def update_bump_distance(self, context):
    """Update callback for bump distance changes."""
    from ..helpers.layer_ui_helpers import update_bump_distance as _impl

    return _impl(self, context)


def update_layer_intensity_value(self, context):
    """Update callback for layer intensity value changes."""
    from ..callbacks.layer_channel_callbacks import (
        update_layer_intensity_value as _impl,
    )

    return _impl(self, context)


def update_divide_rgb_by_alpha(self, context):
    """Update callback for divide RGB by alpha changes."""
    from ..helpers.layer_ui_helpers import update_divide_rgb_by_alpha as _impl

    return _impl(self, context)


def update_flip_backface_normal(self, context):
    """Update callback for flip backface normal changes."""
    from ..helpers.layer_ui_helpers import update_flip_backface_normal as _impl

    return _impl(self, context)


def update_hemi_camera_ray_mask(self, context):
    """Update callback for hemi camera ray mask changes."""
    from ..helpers.layer_ui_helpers import update_hemi_camera_ray_mask as _impl

    return _impl(self, context)


def update_hemi_space(self, context):
    """Update callback for hemi space changes."""
    from ..helpers.layer_ui_helpers import update_hemi_space as _impl

    return _impl(self, context)


def update_hemi_use_prev_normal(self, context):
    """Update callback for hemi use previous normal changes."""
    from ..helpers.layer_ui_helpers import update_hemi_use_prev_normal as _impl

    return _impl(self, context)


def update_image_flip_y(self, context):
    """Update callback for image flip Y changes."""
    from ..helpers.layer_ui_helpers import update_image_flip_y as _impl

    return _impl(self, context)


def update_layer_blur_vector(self, context):
    """Update callback for layer blur vector changes."""
    from ..helpers.layer_ui_helpers import update_layer_blur_vector as _impl

    return _impl(self, context)


def update_layer_blur_vector_factor(self, context):
    """Update callback for layer blur vector factor changes."""
    from ..helpers.layer_ui_helpers import update_layer_blur_vector_factor as _impl

    return _impl(self, context)


def update_layer_channel_override(self, context):
    """Update callback for layer channel override changes."""
    from ..helpers.layer_ui_helpers import update_layer_channel_override as _impl

    return _impl(self, context)


def update_layer_channel_override_1(self, context):
    """Update callback for layer channel override 1 changes."""
    from ..helpers.layer_ui_helpers import update_layer_channel_override_1 as _impl

    return _impl(self, context)


def update_layer_channel_override_vcol_name(self, context):
    """Update callback for layer channel override vcol name changes."""
    from ..helpers.layer_ui_helpers import update_layer_channel_override_vcol_name as _impl

    return _impl(self, context)


def update_layer_channel_use_clamp(self, context):
    """Update callback for layer channel use clamp changes."""
    from ..helpers.layer_ui_helpers import update_layer_channel_use_clamp as _impl

    return _impl(self, context)


def update_layer_channel_vdisp_flip_yz(self, context):
    """Update callback for layer channel vdisp flip YZ changes."""
    from ..helpers.layer_ui_helpers import update_layer_channel_vdisp_flip_yz as _impl

    return _impl(self, context)


def update_layer_channel_voronoi_feature(self, context):
    """Update callback for layer channel voronoi feature changes."""
    from ..helpers.layer_ui_helpers import update_layer_channel_voronoi_feature as _impl

    return _impl(self, context)


def update_override_color_value(self, context):
    """Update callback for override color value changes."""
    from ..callbacks.layer_uv_callbacks import update_override_color_value as _impl

    return _impl(self, context)


def update_layer_color_chortcut(self, context):
    """Update callback for layer color shortcut changes."""
    from ..helpers.layer_ui_helpers import update_layer_color_chortcut as _impl

    return _impl(self, context)


def update_layer_edge_detect_radius(self, context):
    """Update callback for layer edge detect radius changes."""
    from ..helpers.layer_ui_helpers import update_layer_edge_detect_radius as _impl

    return _impl(self, context)


def update_layer_enable(self, context):
    """Update callback for layer enable changes."""
    from ..helpers.layer_ui_helpers import update_layer_enable as _impl

    return _impl(self, context)


def update_layer_input(self, context):
    """Update callback for layer input changes."""
    from ..helpers.layer_ui_helpers import update_layer_input as _impl

    return _impl(self, context)


def update_layer_name(self, context):
    """Update callback for layer name changes."""
    from ..helpers.layer_ui_helpers import update_layer_name as _impl

    return _impl(self, context)


def update_layer_transform(self, context):
    """Update callback for layer transform changes."""
    from ..helpers.layer_ui_helpers import update_layer_transform as _impl

    return _impl(self, context)


def update_layer_uniform_scale_enabled(self, context):
    """Update callback for layer uniform scale enabled changes."""
    from ..helpers.layer_ui_helpers import update_layer_uniform_scale_enabled as _impl

    return _impl(self, context)


def update_layer_use_baked(self, context):
    """Update callback for layer use baked changes."""
    from ..helpers.layer_ui_helpers import update_layer_use_baked as _impl

    return _impl(self, context)


def update_normal_map_type(self, context):
    """Update callback for normal map type changes."""
    from ..helpers.layer_ui_helpers import update_normal_map_type as _impl

    return _impl(self, context)


def update_normal_space(self, context):
    """Update callback for normal space changes."""
    from ..helpers.layer_ui_helpers import update_normal_space as _impl

    return _impl(self, context)


def update_projection_blend(self, context):
    """Update callback for projection blend changes."""
    from ..helpers.layer_ui_helpers import update_projection_blend as _impl

    return _impl(self, context)


def update_texcoord_type(self, context):
    """Update callback for texcoord type changes."""
    from ..helpers.layer_ui_helpers import update_texcoord_type as _impl

    return _impl(self, context)


def update_uv_name(self, context):
    """Update callback for UV name changes."""
    from ..helpers.layer_ui_helpers import update_uv_name as _impl

    return _impl(self, context)


def update_voronoi_feature(self, context):
    """Update callback for voronoi feature changes."""
    from ..helpers.layer_ui_helpers import update_voronoi_feature as _impl

    return _impl(self, context)


def update_write_height(self, context):
    """Update callback for write height changes."""
    from ..helpers.layer_ui_helpers import update_write_height as _impl

    return _impl(self, context)


def update_layer_source_type(self, context):
    """Update callback for layer source type changes."""
    from ..helpers.layer_ui_helpers import update_layer_source_type as _impl

    return _impl(self, context)


def update_layer_projection(self, context):
    """Update callback for layer projection changes."""
    from ..callbacks.layer_visual_callbacks import update_layer_projection as _impl

    return _impl(self, context)


def update_projection_hardness(self, context):
    """Update callback for projection hardness (triplanar blend) changes."""
    from ..callbacks.layer_visual_callbacks import update_projection_hardness as _impl

    return _impl(self, context)


def update_projection_axis(self, context):
    """Update callback for projection axis changes (PLANAR/CYLINDRICAL)."""
    from ..callbacks.layer_visual_callbacks import update_projection_axis as _impl

    return _impl(self, context)


def update_uv_extension(self, context):
    """Update callback for UV extension/wrap mode changes."""
    from ..callbacks.layer_visual_callbacks import update_uv_extension as _impl

    return _impl(self, context)


def update_blend_linked(self, context):
    """Update callback for blend_linked toggle."""
    from ..callbacks.layer_channel_callbacks import update_blend_linked as _impl

    return _impl(self, context)


def update_linked_blend_type(self, context):
    """Update callback for linked_blend_type changes."""
    from ..callbacks.layer_channel_callbacks import update_linked_blend_type as _impl

    return _impl(self, context)


def update_channel_source_transform(self, context):
    """Update callback for channel override source transform changes.

    Updates the mapping node values when transform properties change.
    """
    from ..callbacks.layer_visual_callbacks import update_channel_source_transform as _impl

    return _impl(self, context)
