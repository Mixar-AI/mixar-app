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

from ....common.utils.file_select_utils import (
    file_select_guard, mark_file_select_executed,
)
from ...constants import TURNAROUND_VIEW_MAIN, TURNAROUND_VIEW_NONE
from ...core.turnaround_detect import detect_views
from ...core.turnaround_views import clear_group, find_group_for_image

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
            _select_main_panel(group_id)
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


class MIXIE_OT_moodboard_add_turnaround_view(Operator):
    """Add another image to this multi-view set"""

    bl_idname = "mixie.moodboard_add_turnaround_view"
    bl_label = "Add View"
    bl_description = (
        "Load an image file and add it to the multi-view set. Label it with "
        "the camera angle it shows; it is sent alongside the main image as "
        "one multi-view generation"
    )
    bl_options = {"REGISTER", "UNDO"}

    # Empty when the Model Gen tab has no group yet — one is minted on the
    # fly so a multi-view job can be assembled entirely by hand.
    group_id: bpy.props.StringProperty(default="")
    # 'main' when invoked from the main-image row's file picker.
    view_type: bpy.props.StringProperty(default=TURNAROUND_VIEW_NONE)

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to the view image",
        subtype="FILE_PATH",
    )
    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {"FINISHED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from ...core.turnaround_views import attach_image, set_main_image

        image = self._load(context)
        if image is None:
            return {"CANCELLED"}

        scene = context.scene
        group_id = _ensure_group(context, self.group_id.strip())
        view_type = self.view_type or TURNAROUND_VIEW_NONE

        if attach_image(scene, group_id, image, view_type) is None:
            self.report({"ERROR"}, "Could not add the image to the moodboard")
            return {"CANCELLED"}
        if view_type == TURNAROUND_VIEW_MAIN:
            # Demote whatever was main before — only one is allowed.
            set_main_image(scene, group_id, image)

        _keep_group_resolvable(context, group_id, image)
        mark_file_select_executed(self)
        _redraw_all()
        self.report({"INFO"}, f"Added '{image.name}' to the multi-view set")
        return {"FINISHED"}

    def _load(self, context):
        """Validated, packed image datablock for self.filepath (or None)."""
        import os

        if not self.filepath:
            self.report({"WARNING"}, "No file selected")
            return None
        try:
            path = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({"ERROR"}, f"Invalid file path: {e}")
            return None
        if not os.path.isfile(path):
            self.report({"ERROR"}, f"File not found: {path}")
            return None
        try:
            image = bpy.data.images.load(path, check_existing=True)
            # Packed so the view survives a .blend reload — a hand-added view
            # carries its pixels inline at submit time, unlike detected crops.
            image.pack()
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {e}")
            return None
        return image


class MIXIE_OT_moodboard_remove_turnaround_view(Operator):
    """Remove this image from the multi-view set"""

    bl_idname = "mixie.moodboard_remove_turnaround_view"
    bl_label = "Remove View"
    bl_description = (
        "Drop this image from the multi-view set. It stays on the moodboard, "
        "it is just no longer sent as one of the views"
    )
    bl_options = {"REGISTER", "UNDO"}

    group_id: bpy.props.StringProperty(default="")
    image_name: bpy.props.StringProperty(default="")

    def execute(self, context):
        from ...core.turnaround_views import detach_image

        image = bpy.data.images.get(self.image_name.strip())
        if image is None:
            self.report({"WARNING"}, "View image not found")
            return {"CANCELLED"}
        if not detach_image(context.scene, self.group_id.strip(), image):
            self.report({"WARNING"}, "View is not part of this set")
            return {"CANCELLED"}
        _redraw_all()
        self.report({"INFO"}, f"Removed '{image.name}' from the multi-view set")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Group / tab plumbing
# ---------------------------------------------------------------------------

def _model_gen_tab(scene):
    """The Model Gen sidebar tab properties, or None."""
    sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
    return getattr(sidebar, 'tab_image_to_3d', None) if sidebar else None


def _point_tab_at(scene, image):
    """Make *image* the Model Gen tab's input, whichever source it uses.

    BOTH paths are re-pointed on purpose. ``find_group_for_image`` can only
    resolve a group from a moodboard item, so an image chosen through the file
    picker (``tab.reference_image``) never resolves one — leaving it in place
    let a freshly detected sheet be submitted whole as a single image while
    the panel still offered "Detect Views".
    """
    if image is None:
        return
    for item in scene.mixie_moodboard_images:
        item.selected = (item.image == image)
    tab = _model_gen_tab(scene)
    if tab is not None and not getattr(tab, 'use_selected_image', False):
        tab.reference_image = image


def _keep_group_resolvable(context, group_id: str, fallback_image) -> None:
    """Ensure the tab's input still resolves to *group_id* after an edit."""
    from ...core.turnaround_views import main_item
    from ..sidebar_ui_helpers import get_image_to_3d_input_image

    scene = context.scene
    current = get_image_to_3d_input_image(context)
    if find_group_for_image(scene, current) == group_id:
        return
    main = main_item(scene, group_id)
    _point_tab_at(scene, main.image if main is not None else fallback_image)


def _ensure_group(context, explicit_group: str) -> str:
    """The group Add View should target, minting one when there is none.

    A brand-new group is seeded with the tab's current input image as its
    main view, so the very first hand-added view already has something to be
    a companion of.
    """
    from ...core.turnaround_views import attach_image, new_group_id
    from ..sidebar_ui_helpers import get_image_to_3d_input_image

    if explicit_group:
        return explicit_group

    scene = context.scene
    current = get_image_to_3d_input_image(context)
    existing = find_group_for_image(scene, current)
    if existing:
        return existing

    group_id = new_group_id()
    if current is not None:
        attach_image(scene, group_id, current, TURNAROUND_VIEW_MAIN)
    return group_id


def _select_main_panel(group_id: str):
    """Point the Model Gen tab's input at the group's main crop.

    The user's next Generate press then naturally takes the multi-view path
    without them having to hunt for the right crop on the canvas.
    """
    from ...core.turnaround_views import main_item

    scene = bpy.context.scene
    item = main_item(scene, group_id)
    if item is None:
        return
    _point_tab_at(scene, item.image)


classes = (
    MIXIE_OT_moodboard_detect_views,
    MIXIE_OT_moodboard_clear_turnaround,
    MIXIE_OT_moodboard_add_turnaround_view,
    MIXIE_OT_moodboard_remove_turnaround_view,
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
