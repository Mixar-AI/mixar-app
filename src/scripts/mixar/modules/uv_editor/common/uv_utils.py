# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Editor Utilities

Common utility functions and decorators for UV editor operators.
Reduces code duplication across operator modules.
"""

import bpy
from functools import wraps


# ============================================================
# Context Getters
# ============================================================

def get_mixar_uv_image_editor(context):
    """Find the IMAGE_EDITOR area in MIXAR_UV mode.

    Args:
        context: Blender context

    Returns:
        Area or None: The IMAGE_EDITOR area in MIXAR_UV mode, or None if not found
    """
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            sima = area.spaces.active
            if sima and sima.mode == 'MIXAR_UV':
                return area
    return None


def get_window_region(area):
    """Get the WINDOW region from an area.

    Args:
        area: Blender area

    Returns:
        Region or None: The WINDOW region, or None if not found
    """
    if not area:
        return None
    for region in area.regions:
        if region.type == 'WINDOW':
            return region
    return None


# ============================================================
# Common Poll Functions
# ============================================================

def poll_mixar_uv_mode(context):
    """Poll function: Check if MIXAR_UV mode is active.

    Args:
        context: Blender context

    Returns:
        bool: True if MIXAR_UV mode is active
    """
    area = get_mixar_uv_image_editor(context)
    return area is not None


def poll_mixar_uv_edit_mode(context):
    """Poll function: Check if MIXAR_UV mode is active and object is in edit mode.

    Args:
        context: Blender context

    Returns:
        bool: True if MIXAR_UV mode is active and mesh object is in edit mode
    """
    area = get_mixar_uv_image_editor(context)
    if not area:
        return False
    obj = context.active_object
    return obj and obj.type == 'MESH' and obj.mode == 'EDIT'


def clear_mixar_uv_active_panel(context):
    """Reset `wm.mixar_uv_ui.active_panel` to 'NONE' and force every
    IMAGE_EDITOR area / region to repaint *immediately*.

    Called from every Mixar UV tool-activation operator
    (`mixar.activate_*`) so that picking a workspace tool from the left
    toolbar — or re-clicking the tool that's already active — deselects
    whichever header-tab panel (UV Set / Unwrap / Texel / Layout /
    Image / Material / Export) was previously open. The tool-based
    sidebar panel (Selection / UV Sculpt Tools / Tools / Functions /
    Annotate) replaces it.

    Implementation note — we explicitly assign `= 'NONE'` instead of
    `property_unset(...)`. `property_unset` resets the value back to
    its RNA default but **does not** fire the `update=` callback on
    the property, so `_active_panel_update` (which tag_redraws the
    header where the panel tabs live) never runs and the artist sees
    a stale "depressed" state on the tab they just abandoned until
    the next unrelated event triggers a redraw. Direct assignment
    always fires the `update=` callback.
    """
    wm = getattr(context, 'window_manager', None)
    if wm is None:
        return
    uv_ui = getattr(wm, 'mixar_uv_ui', None)
    if uv_ui is None:
        return
    if uv_ui.active_panel != 'NONE':
        uv_ui.active_panel = 'NONE'

    # Prefer the active screen: tool activation usually comes from the
    # same editor that needs repainting. Fall back to all windows only
    # when the caller has no usable screen in context.
    screen = getattr(context, 'screen', None)
    if screen is not None:
        for area in screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()
                for region in area.regions:
                    region.tag_redraw()
        return

    for wm_iter in bpy.data.window_managers:
        for window in wm_iter.windows:
            for area in window.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    area.tag_redraw()
                    for region in area.regions:
                        region.tag_redraw()


def poll_mixar_uv_with_image(context):
    """Poll function: Check if MIXAR_UV mode is active and has an image.

    Args:
        context: Blender context

    Returns:
        bool: True if MIXAR_UV mode is active and has an image
    """
    area = get_mixar_uv_image_editor(context)
    if not area:
        return False
    sima = area.spaces.active
    return sima and sima.image is not None


def poll_mixar_uv_with_packed_image(context):
    """Poll function: Check if MIXAR_UV mode has a packed image.

    Args:
        context: Blender context

    Returns:
        bool: True if MIXAR_UV mode has a packed image
    """
    area = get_mixar_uv_image_editor(context)
    if not area:
        return False
    sima = area.spaces.active
    return sima and sima.image and sima.image.packed_file is not None


def poll_mixar_uv_with_unpacked_image(context):
    """Poll function: Check if MIXAR_UV mode has an unpacked image.

    Args:
        context: Blender context

    Returns:
        bool: True if MIXAR_UV mode has an unpacked image
    """
    area = get_mixar_uv_image_editor(context)
    if not area:
        return False
    sima = area.spaces.active
    return sima and sima.image and not sima.image.packed_file


# ============================================================
# Context Override Helpers
# ============================================================

def with_uv_context(func):
    """Decorator: Execute operator with UV editor area context override.

    This decorator automatically:
    - Gets the MIXAR_UV IMAGE_EDITOR area
    - Overrides context with the area
    - Calls the wrapped function with area as first argument
    - Returns {'CANCELLED'} if area not found

    Usage:
        @with_uv_context
        def execute(self, context, area):
            # area is automatically provided
            with context.temp_override(area=area):
                bpy.ops.uv.some_operation()
            return {'FINISHED'}
    """
    @wraps(func)
    def wrapper(self, context):
        area = get_mixar_uv_image_editor(context)
        if not area:
            return {'CANCELLED'}
        return func(self, context, area)
    return wrapper


def with_uv_context_and_region(func):
    """Decorator: Execute operator with UV editor area and WINDOW region context override.

    This decorator automatically:
    - Gets the MIXAR_UV IMAGE_EDITOR area
    - Gets the WINDOW region from the area
    - Calls the wrapped function with area and region as arguments
    - Returns {'CANCELLED'} if area or region not found

    Usage:
        @with_uv_context_and_region
        def execute(self, context, area, region):
            # area and region are automatically provided
            with context.temp_override(area=area, region=region):
                bpy.ops.transform.translate(...)
            return {'FINISHED'}
    """
    @wraps(func)
    def wrapper(self, context):
        area = get_mixar_uv_image_editor(context)
        if not area:
            return {'CANCELLED'}
        region = get_window_region(area)
        if not region:
            return {'CANCELLED'}
        return func(self, context, area, region)
    return wrapper


# ============================================================
# Operator Property Helpers
# ============================================================

def get_operator_properties(context, operator_idname):
    """Get the last used properties for a Blender operator.

    Args:
        context: Blender context
        operator_idname: Operator ID name (e.g., "uv.pack_islands")

    Returns:
        OperatorProperties: The operator properties
    """
    wm = context.window_manager
    return wm.operator_properties_last(operator_idname)


# ============================================================
# Execution Helpers
# ============================================================

def execute_uv_operator(context, operator_name, **kwargs):
    """Execute a UV operator with automatic area context override.

    Args:
        context: Blender context
        operator_name: Operator name (e.g., "uv.select_all")
        **kwargs: Operator arguments

    Returns:
        set: Operator result ({'FINISHED'}, {'CANCELLED'}, etc.)
    """
    area = get_mixar_uv_image_editor(context)
    if not area:
        return {'CANCELLED'}

    with context.temp_override(area=area):
        # Split operator name to get module and function
        parts = operator_name.split('.')
        if len(parts) == 2:
            module_name, op_name = parts
            op = getattr(getattr(bpy.ops, module_name), op_name)
            return op(**kwargs)

    return {'CANCELLED'}


def execute_uv_operator_with_region(context, operator_name, **kwargs):
    """Execute a UV operator with area and WINDOW region context override.

    Args:
        context: Blender context
        operator_name: Operator name (e.g., "transform.translate")
        **kwargs: Operator arguments

    Returns:
        set: Operator result ({'FINISHED'}, {'CANCELLED'}, etc.)
    """
    area = get_mixar_uv_image_editor(context)
    if not area:
        return {'CANCELLED'}

    region = get_window_region(area)
    if not region:
        return {'CANCELLED'}

    with context.temp_override(area=area, region=region):
        # Split operator name to get module and function
        parts = operator_name.split('.')
        if len(parts) == 2:
            module_name, op_name = parts
            op = getattr(getattr(bpy.ops, module_name), op_name)
            return op(**kwargs)

    return {'CANCELLED'}
