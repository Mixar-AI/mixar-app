# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for preferences panel UI drawing."""


def draw_image_settings(layout, prefs):
    """Draw the image settings section.

    Args:
        layout: Blender layout object
        prefs: Mixar paint preferences
    """
    box = layout.box()
    box.label(text="Image Settings", icon="IMAGE_DATA")
    col = box.column(align=True)
    col.prop(prefs, "default_new_image_size")
    col.prop(prefs, "image_atlas_size")
    col.prop(prefs, "hdr_image_atlas_size")
    col.prop(prefs, "unique_image_atlas_per_mp")


def draw_ui_options(layout, prefs):
    """Draw the UI options section.

    Args:
        layout: Blender layout object
        prefs: Mixar paint preferences
    """
    box = layout.box()
    box.label(text="UI Options", icon="PREFERENCES")
    col = box.column(align=True)
    col.prop(prefs, "use_image_preview")
    col.prop(prefs, "skip_property_popups")
    col.prop(prefs, "icons")
    col.prop(prefs, "layer_list_mode")


def draw_rendering_options(layout, prefs):
    """Draw the rendering options section.

    Args:
        layout: Blender layout object
        prefs: Mixar paint preferences
    """
    box = layout.box()
    box.label(text="Rendering Options", icon="SHADING_RENDERED")
    col = box.column(align=True)
    col.prop(prefs, "make_preview_mode_srgb")
    col.prop(prefs, "parallax_without_baked")
    col.prop(prefs, "default_bake_device")


def draw_layer_node_options(layout, prefs):
    """Draw the default layer/node options section.

    Args:
        layout: Blender layout object
        prefs: Mixar paint preferences
    """
    box = layout.box()
    box.label(text="Default Layer/Node Options", icon="NODE")
    col = box.column(align=True)
    col.prop(prefs, "enable_baked_outside_by_default")
    col.prop(prefs, "enable_uniform_uv_scale_by_default")
    col.prop(prefs, "enable_auto_udim_detection")
    col.prop(prefs, "default_image_resolution")


def draw_update_settings(layout, prefs):
    """Draw the update settings section.

    Args:
        layout: Blender layout object
        prefs: Mixar paint preferences
    """
    box = layout.box()
    box.label(text="Update Settings", icon="FILE_REFRESH")
    col = box.column(align=True)
    col.prop(prefs, "auto_check_update")

    # Show interval settings if auto-check is enabled
    if prefs.auto_check_update:
        col.separator(factor=0.5)
        col.prop(prefs, "updater_interval_months")
        col.prop(prefs, "updater_interval_days")
        col.prop(prefs, "updater_interval_hours")
        col.prop(prefs, "updater_interval_minutes")


def draw_developer_options(layout, prefs):
    """Draw the developer options section.

    Args:
        layout: Blender layout object
        prefs: Mixar paint preferences
    """
    box = layout.box()
    box.label(text="Developer Options", icon="CONSOLE")
    col = box.column(align=True)
    col.prop(prefs, "developer_mode")
    col.prop(prefs, "show_experimental")
    col.prop(prefs, "always_evaluate_frame")


def draw_danger_zone(layout):
    """Draw the danger zone section with destructive operations.

    Args:
        layout: Blender layout object
    """
    from ...core.node.node_utils import get_active_mpaint_node

    # Only show if there's an active mpaint node
    if not get_active_mpaint_node():
        return

    box = layout.box()
    box.label(text="Danger Zone", icon="ERROR")
    col = box.column(align=True)
    col.operator("wm.m_remove_mp_node", text="Remove Layer Based Material", icon="TRASH")
