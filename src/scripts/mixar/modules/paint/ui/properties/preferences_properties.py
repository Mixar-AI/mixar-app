# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property definitions for Mixar preferences (migrated from Mixar Paint addon preferences)"""

import bpy
from bpy.props import (
    BoolProperty,
    IntProperty,
    EnumProperty,
)


def _save_on_update(self, context):
    """Update callback that persists preferences whenever a value changes."""
    from ...utils.preferences_config import save_preferences
    save_preferences()


class MixarPaintPreferences(bpy.types.PropertyGroup):
    """Preferences for Mixar paint system (migrated from Mixar Paint addon preferences)"""

    # ========== IMAGE SETTINGS ==========

    default_new_image_size: IntProperty(
        name="Default Image Size",
        description="Custom default image size for new textures",
        default=1024,
        min=64,
        max=16384,
        subtype='PIXEL',
        update=_save_on_update,
    )

    image_atlas_size: IntProperty(
        name="Image Atlas Size",
        description="Size of the image atlas for texture packing",
        default=8192,
        min=2048,
        max=16384,
        subtype='PIXEL',
        update=_save_on_update,
    )

    hdr_image_atlas_size: IntProperty(
        name="HDR Image Atlas Size",
        description="Size of the HDR image atlas",
        default=4096,
        min=1024,
        max=8192,
        subtype='PIXEL',
        update=_save_on_update,
    )

    unique_image_atlas_per_mp: BoolProperty(
        name="Unique Atlas Per Tree",
        description="Use a unique image atlas for each node tree",
        default=True,
        update=_save_on_update,
    )

    # ========== DEVELOPER OPTIONS ==========

    developer_mode: BoolProperty(
        name="Developer Mode",
        description="Show developer-only menus and options",
        default=False,
        update=_save_on_update,
    )

    show_experimental: BoolProperty(
        name="Show Experimental Features",
        description="Display experimental features (may be unstable)",
        default=False,
        update=_save_on_update,
    )

    # ========== UI OPTIONS ==========

    use_image_preview: BoolProperty(
        name="Image Previews",
        description="Enable image thumbnails in layers list (may affect performance)",
        default=False,
        update=_save_on_update,
    )

    skip_property_popups: BoolProperty(
        name="Skip Property Popups",
        description="Suppress informational popups unless Shift is held",
        default=False,
        update=_save_on_update,
    )

    icons: EnumProperty(
        name="Icon Set",
        description="Choose which icon set to use",
        items=[
            ('DEFAULT', "Modern", "Use modern Blender icons"),
            ('LEGACY', "Legacy", "Use legacy icon set"),
        ],
        default='DEFAULT',
        update=_save_on_update,
    )

    layer_list_mode: EnumProperty(
        name="Layer List Mode",
        description="Choose how the layer list is displayed",
        items=[
            ('DYNAMIC', "Dynamic", "Dynamic layer list layout"),
            ('CLASSIC', "Classic", "Classic layer list layout"),
            ('BOTH', "Both", "Show both dynamic and classic layouts"),
        ],
        default='DYNAMIC',
        update=_save_on_update,
    )

    # ========== RENDERING OPTIONS ==========

    make_preview_mode_srgb: BoolProperty(
        name="sRGB Preview Mode",
        description="Use sRGB color space in preview mode",
        default=True,
        update=_save_on_update,
    )

    parallax_without_baked: BoolProperty(
        name="Parallax Without Baking",
        description="Allow parallax mapping without requiring baked textures",
        default=False,
        update=_save_on_update,
    )

    default_bake_device: EnumProperty(
        name="Default Bake Device",
        description="Default device to use for texture baking",
        items=[
            ('DEFAULT', "Default", "Use system default device"),
            ('CPU', "CPU", "Force CPU baking"),
            ('GPU', "GPU", "Force GPU baking"),
        ],
        default='DEFAULT',
        update=_save_on_update,
    )

    # ========== DEFAULT LAYER/NODE OPTIONS ==========

    enable_baked_outside_by_default: BoolProperty(
        name="Enable Baked Outside by Default",
        description="New nodes will have 'baked outside' enabled by default",
        default=False,
        update=_save_on_update,
    )

    enable_uniform_uv_scale_by_default: BoolProperty(
        name="Uniform UV Scale by Default",
        description="Enable uniform UV scaling by default for new layers and masks",
        default=False,
        update=_save_on_update,
    )

    enable_auto_udim_detection: BoolProperty(
        name="Auto UDIM Detection",
        description="Automatically detect UDIM tiles for textures",
        default=True,
        update=_save_on_update,
    )

    default_image_resolution: EnumProperty(
        name="Default Image Resolution",
        description="Default resolution mode for new images",
        items=[
            ('DEFAULT', "Default", "Use default resolution"),
            ('CUSTOM', "Custom", "Use custom resolution from settings"),
        ],
        default='DEFAULT',
        update=_save_on_update,
    )

    # ========== UPDATE SETTINGS ==========

    auto_check_update: BoolProperty(
        name="Auto-Check for Updates",
        description="Automatically check for addon updates",
        default=True,
        update=_save_on_update,
    )

    updater_interval_months: IntProperty(
        name="Update Check Interval (Months)",
        description="Number of months between update checks",
        default=0,
        min=0,
        update=_save_on_update,
    )

    updater_interval_days: IntProperty(
        name="Update Check Interval (Days)",
        description="Number of days between update checks",
        default=1,
        min=0,
        update=_save_on_update,
    )

    updater_interval_hours: IntProperty(
        name="Update Check Interval (Hours)",
        description="Number of hours between update checks",
        default=0,
        min=0,
        update=_save_on_update,
    )

    updater_interval_minutes: IntProperty(
        name="Update Check Interval (Minutes)",
        description="Number of minutes between update checks",
        default=1,
        min=0,
        update=_save_on_update,
    )

    # ========== MATERIAL LIBRARY UI ==========

    material_ui_columns: IntProperty(
        name="Material Library Columns",
        description="Number of columns in the procedural material library popup",
        default=4,
        min=1,
        max=10,
        update=_save_on_update,
    )

    material_image_scale: IntProperty(
        name="Material Thumbnail Scale",
        description="Scale of material thumbnails in the library",
        default=3,
        min=1,
        max=10,
        update=_save_on_update,
    )

    # ========== MISC OPTIONS ==========

    always_evaluate_frame: BoolProperty(
        name="Always Evaluate Frame",
        description="Evaluate node tree on every frame change",
        default=False,
        update=_save_on_update,
    )


# Classes for registration
classes = (
    MixarPaintPreferences,
)


def register():
    """Register preferences properties.

    This function is idempotent - safe to call multiple times.
    """
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise

    # Register preferences as scene property
    if not hasattr(bpy.types.Scene, 'mixar_paint_preferences'):
        bpy.types.Scene.mixar_paint_preferences = bpy.props.PointerProperty(type=MixarPaintPreferences)


def unregister():
    """Unregister preferences properties"""
    # Unregister scene property
    if hasattr(bpy.types.Scene, 'mixar_paint_preferences'):
        del bpy.types.Scene.mixar_paint_preferences

    # Unregister classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
