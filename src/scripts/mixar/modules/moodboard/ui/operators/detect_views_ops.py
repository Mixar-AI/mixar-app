# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect Views Operators

Turnaround / model-sheet handling for the Model Gen tab. ``Detect Views``
sends the selected moodboard image to the backend, which splits it into
labelled per-view crops; those crops land back on the moodboard sharing a
``turnaround_group`` and are then submitted as ONE multi-view job.

The request runs on the shared async API queue, so the UI thread is never
blocked; progress is surfaced through ``scene.mixie_detect_views_running``.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core.turnaround_views import (
    clear_group, detect_views, find_group_for_image,
)

logger = get_logger(__name__)


def _redraw_all():
    """Trigger redraw of all MIXIE areas and sidebars."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'MIXIE', 'VIEW_3D'}:
                area.tag_redraw()


def _set_running(value: bool):
    """Flip the in-flight flag used to disable the button while detecting."""
    try:
        bpy.context.scene.mixie_detect_views_running = value
    except Exception:
        pass


def _set_status(message: str):
    """Store a short status line for the Model Gen tab to display."""
    try:
        bpy.context.scene.mixie_detect_views_status = message
    except Exception:
        pass


def _resolve_selected_image(context):
    """The image Detect Views operates on when no explicit name is given.

    Delegates to the shared Model Gen input resolution so the sidebar button
    and this operator can never disagree. Agent invocations pass ``image_name``
    instead and never reach this — see the execute() below.
    """
    from ..sidebar_ui_helpers import get_image_to_3d_input_image
    return get_image_to_3d_input_image(context)


class MIXIE_OT_moodboard_detect_views(Operator):
    """Split a turnaround / model sheet into labelled per-view crops"""

    bl_idname = "mixie.moodboard_detect_views"
    bl_label = "Detect Views"
    bl_description = (
        "Detect multiple camera angles in the selected image and split it "
        "into labelled per-view crops for a single multi-view 3D generation"
    )
    bl_options = {"REGISTER"}

    # Direct-invocation property (agent scripts). When non-empty the image is
    # looked up by name in bpy.data.images and the moodboard selection is not
    # consulted at all — the agent has no selection to read.
    image_name: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        # Deliberately does NOT require a moodboard selection: poll() cannot
        # see operator properties, so gating on selection here would block
        # agent calls that pass an explicit image_name. The sidebar button is
        # gated on the selection separately (ui/turnaround_drawer.py).
        return not getattr(context.scene, 'mixie_detect_views_running', False)

    def execute(self, context):
        name = self.image_name.strip()
        if name:
            # Explicit image: never fall back to the selection on a bad name,
            # or the agent would silently operate on whatever the user clicked.
            image = bpy.data.images.get(name)
            if image is None:
                self.report(
                    {'ERROR'}, f"Image '{name}' not found in bpy.data.images")
                return {'CANCELLED'}
        else:
            image = _resolve_selected_image(context)
            if image is None:
                self.report({'WARNING'}, "Select an image in the moodboard first")
                return {'CANCELLED'}

        existing = find_group_for_image(context.scene, image)
        if existing:
            self.report({'INFO'}, "This image is already part of a detected group")
            return {'CANCELLED'}

        scene = context.scene
        # detect_views can fail synchronously (e.g. unreadable pixels) before
        # any request goes out; track that so this operator still reports.
        failed_early = []

        def on_done(group_id, count):
            _set_running(False)
            _select_front_panel(group_id)
            logger.debug("[DetectViews] %s panels in group %s", count, group_id)
            _set_status(f"Detected {count} views")
            _redraw_all()

        def on_error(message):
            # Reuses the shared async-error helper: clears the in-flight flag,
            # stores the message for the panel, and pops a dialog.
            from mixar.modules.common.utils.mixie_space_utils import (
                show_generation_error,
            )
            failed_early.append(message)
            show_generation_error(
                scene, "Detect Views", message,
                "mixie_detect_views_running", "mixie_detect_views_status",
            )

        def on_not_turnaround():
            # Not an error: the image is an ordinary single image and the
            # existing single-image path applies unchanged.
            _set_running(False)
            _set_status("No multiple views detected")
            _redraw_all()

        _set_running(True)
        _set_status("Detecting views...")
        _redraw_all()
        try:
            detect_views(image, on_done, on_error, on_not_turnaround)
        except Exception as e:
            _set_running(False)
            _set_status("")
            logger.error("[DetectViews] Failed to start: %s", e, exc_info=True)
            self.report({'ERROR'}, f"Failed to start view detection: {e}")
            return {'CANCELLED'}

        if failed_early:
            self.report({'ERROR'}, failed_early[0])
            return {'CANCELLED'}

        self.report({'INFO'}, "Detecting views...")
        return {'FINISHED'}


class MIXIE_OT_moodboard_clear_turnaround(Operator):
    """Ungroup detected views so the image generates as a single image"""

    bl_idname = "mixie.moodboard_clear_turnaround"
    bl_label = "Clear Detected Views"
    bl_description = (
        "Detach these crops from their turnaround group. The images stay on "
        "the moodboard but generate individually again"
    )
    bl_options = {"REGISTER", "UNDO"}

    group_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        group_id = self.group_id.strip()
        if not group_id:
            self.report({'WARNING'}, "No turnaround group specified")
            return {'CANCELLED'}
        cleared = clear_group(context.scene, group_id)
        if not cleared:
            self.report({'WARNING'}, "Turnaround group not found")
            return {'CANCELLED'}
        _redraw_all()
        self.report({'INFO'}, f"Ungrouped {cleared} views")
        return {'FINISHED'}


def _select_front_panel(group_id: str):
    """Make the group's front crop the active moodboard selection.

    The user's next Generate press then naturally takes the multi-view path
    without them having to hunt for the right crop on the canvas.
    """
    from ...constants import TURNAROUND_VIEW_FRONT
    from ...core.turnaround_views import group_items

    scene = bpy.context.scene
    items = group_items(scene, group_id)
    if not items:
        return
    front = items[0]
    if front.view_type != TURNAROUND_VIEW_FRONT:
        return
    for item in scene.mixie_moodboard_images:
        item.selected = (item.image == front.image)


classes = (
    MIXIE_OT_moodboard_detect_views,
    MIXIE_OT_moodboard_clear_turnaround,
)


def register():
    """Register operator classes and the transient detect-views scene state"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
    bpy.types.Scene.mixie_detect_views_running = bpy.props.BoolProperty(
        name="Detecting Views",
        description="A view-detection request is in flight",
        default=False,
        options={'SKIP_SAVE'},
    )
    bpy.types.Scene.mixie_detect_views_status = bpy.props.StringProperty(
        name="Detect Views Status",
        description="Last view-detection status message",
        default="",
        options={'SKIP_SAVE'},
    )


def unregister():
    """Unregister operator classes and the transient detect-views scene state"""
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
    for prop in ("mixie_detect_views_running", "mixie_detect_views_status"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
