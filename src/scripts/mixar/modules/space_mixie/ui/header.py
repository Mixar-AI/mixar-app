# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Space Header

Header definition for the Mixie space with loading animation support.
"""

import bpy
from bpy.types import Header, Menu
import time

# Animation state for loading indicator
_loading_animation_state = {
    'frame': 0,
    'last_update': 0.0,
    'timer_running': False,
}

# Animation frames for the sliding bar effect
# Using Unicode block characters for a smooth slider animation
_ANIMATION_FRAMES = [
    "[■□□□□]",
    "[□■□□□]",
    "[□□■□□]",
    "[□□□■□]",
    "[□□□□■]",
    "[□□□■□]",
    "[□□■□□]",
    "[□■□□□]",
]


def _get_active_generation_name(context):
    """
    Get the name of the currently active generation operation.
    Returns (is_active, name) tuple.
    """
    scene = context.scene

    # Check each generation flag and return appropriate name
    if getattr(scene, 'mixie_imagegen_is_generating', False):
        return True, "Generating Image"
    if getattr(scene, 'mixie_lookdev_is_generating', False):
        return True, "Generating Blockout Render"
    if getattr(scene, 'mixie_lookdev360_is_generating', False):
        return True, "Generating PBR Maps"
    if getattr(scene, 'mixie_image_to_3d_is_generating', False):
        return True, "Generate Model"
    if getattr(scene, 'mixie_mesh_segment_is_processing', False):
        return True, "Segmenting Mesh"
    if getattr(scene, 'mixie_scene_recon_is_generating', False):
        return True, "Generating Scene"
    if getattr(scene, 'mixie_retopology_is_generating', False):
        return True, "Performing Retopology"

    # Check if scene generation is in progress (Segment to 3D)
    try:
        from ...moodboard.core.scene_gen_manager import get_scene_gen_manager
        manager = get_scene_gen_manager()
        if manager.has_active_jobs():
            return True, "Segment to 3D"
    except Exception:
        pass

    return False, ""


def _has_moodboard_content(context):
    """Check if there is any content in the moodboard."""
    scene = context.scene
    has_content = False
    if hasattr(scene, 'mixie_moodboard_images') and len(scene.mixie_moodboard_images) > 0:
        has_content = True
    if hasattr(scene, 'mixie_moodboard_textboxes') and len(scene.mixie_moodboard_textboxes) > 0:
        has_content = True
    return has_content


def _loading_timer_callback():
    """Timer callback to update animation frame and trigger redraw."""
    global _loading_animation_state

    # Get current time
    current_time = time.time()

    # Update animation frame every 150ms for smooth animation
    if current_time - _loading_animation_state['last_update'] >= 0.15:
        _loading_animation_state['frame'] = (
            (_loading_animation_state['frame'] + 1) % len(_ANIMATION_FRAMES)
        )
        _loading_animation_state['last_update'] = current_time

        # Trigger redraw of all MIXIE areas
        wm = getattr(bpy.context, 'window_manager', None)
        if wm:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type == 'MIXIE':
                        area.tag_redraw()

    # Check if any generation is still active
    try:
        is_active, _ = _get_active_generation_name(bpy.context)

        if is_active:
            # Continue timer
            return 0.1  # Check every 100ms
        else:
            # Stop timer
            _loading_animation_state['timer_running'] = False
            # Final redraw to clear the loading indicator
            wm = getattr(bpy.context, 'window_manager', None)
            if wm:
                for window in wm.windows:
                    for area in window.screen.areas:
                        if area.type == 'MIXIE':
                            area.tag_redraw()
            return None
    except Exception:
        # Context may not be available, stop timer
        _loading_animation_state['timer_running'] = False
        return None


def _ensure_loading_timer():
    """Ensure the loading animation timer is running."""
    global _loading_animation_state

    if not _loading_animation_state['timer_running']:
        _loading_animation_state['timer_running'] = True
        _loading_animation_state['last_update'] = time.time()
        bpy.app.timers.register(_loading_timer_callback, first_interval=0.1)


class MIXIE_MT_view(Menu):
    bl_label = "View"

    def draw(self, context):
        layout = self.layout

        # Toggle toolbar visibility
        layout.operator(
            "screen.region_toggle",
            text="Toolbar",
            icon='CHECKBOX_HLT' if MIXIE_HT_header._is_toolbar_visible(context) else 'CHECKBOX_DEHLT'
        ).region_type = 'TOOLS'

        # Toggle sidebar visibility
        layout.operator(
            "screen.region_toggle",
            text="Sidebar",
            icon='CHECKBOX_HLT' if MIXIE_HT_header._is_sidebar_visible(context) else 'CHECKBOX_DEHLT'
        ).region_type = 'UI'


class MIXIE_HT_header(Header):
    bl_space_type = 'MIXIE'

    @staticmethod
    def _is_toolbar_visible(context):
        for region in context.area.regions:
            if region.type == 'TOOLS':
                # Region is visible if it has non-zero width
                return region.width > 0
        return False

    @staticmethod
    def _is_sidebar_visible(context):
        for region in context.area.regions:
            if region.type == 'UI':
                # Region is visible if it has non-zero width
                return region.width > 0
        return False

    def draw(self, context):
        layout = self.layout
        layout.template_header()

        layout.label(text="Moodboard")

        # Add View menu (commented out)
        # layout.menu("MIXIE_MT_view")

        # Check if any generation is in progress
        is_generating, gen_name = _get_active_generation_name(context)

        if is_generating:
            # Ensure timer is running for animation
            _ensure_loading_timer()

            # Add spacing before loading indicator
            layout.separator_spacer()

            # Create a row for the loading indicator
            row = layout.row(align=True)
            row.alert = False

            # Get current animation frame
            frame = _loading_animation_state['frame']
            animation_text = _ANIMATION_FRAMES[frame]

            # Draw the loading indicator with operation name
            row.label(text=f"{gen_name} {animation_text}", icon='SORTTIME')

        # Show "Clear Moodboard" button when there is content in moodboard
        if _has_moodboard_content(context):
            layout.separator_spacer()
            row = layout.row(align=True)
            row.operator(
                "mixie.clear_moodboard",
                text="Clear Moodboard",
                icon='X'
            )


classes = (
    MIXIE_MT_view,
    MIXIE_HT_header,
)
