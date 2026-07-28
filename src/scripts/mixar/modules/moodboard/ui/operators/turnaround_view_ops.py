# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multi-View Set Operators

Everything that edits the Model Gen tab's multi-view (turnaround) set:
``Add Selected`` (the primary path — takes the moodboard selection and
auto-assigns angles), the secondary file picker, per-row remove and promote,
and the group-wide clear. Detection itself lives in ``detect_views_ops.py``.

The set holds COMPANIONS ONLY — the vendor takes one frontal image plus up to
seven angles, and the frontal image is the tab's Input Image. ``Promote`` is
how the input image gets swapped: the promoted view leaves the set (there is
no vendor angle that describes a front view, so it cannot stay), and the old
input image simply becomes an ordinary untagged moodboard image again.

The active group id lives on the tab (see ``core/turnaround_views.py``), so
these operators work identically whichever image source the tab is using.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ....common.utils.file_select_utils import (
    file_select_guard, mark_file_select_executed,
)
from ...constants import TURNAROUND_MAX_COMPANIONS
from ...core.turnaround_views import (
    add_images_as_views,
    allowed_view_types,
    attach_image,
    clear_group,
    detach_image,
    eligible_selected_images,
    get_active_group,
    new_group_id,
    next_free_view_type,
    remaining_capacity,
    set_active_group,
    set_tab_input_image,
)

logger = get_logger(__name__)


def _redraw_all():
    """Trigger redraw of all MIXIE areas and sidebars."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'MIXIE', 'VIEW_3D'}:
                area.tag_redraw()


def _model_slug(scene) -> str:
    """Model slug the tab is currently set to ("" when unresolved).

    Drives which angles may be assigned: Hunyuan 3.0 takes only left / right
    / back, so auto-assignment must not hand out a 3.1-only angle there.
    """
    sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
    tab = getattr(sidebar, 'tab_image_to_3d', None) if sidebar else None
    return (getattr(tab, 'model', '') or "") if tab else ""


def _ensure_group(scene) -> str:
    """The group being edited, minting and storing one when there is none.

    Nothing is seeded into it: the input image is not a member, so a brand-new
    set starts empty and the caller fills it.
    """
    group_id = get_active_group(scene)
    if group_id:
        return group_id
    group_id = new_group_id()
    set_active_group(scene, group_id)
    return group_id


def _input_image(context):
    """The tab's current Input Image, or None."""
    from ..sidebar_ui_helpers import get_image_to_3d_input_image
    return get_image_to_3d_input_image(context)


class MIXIE_OT_moodboard_add_selected_views(Operator):
    """Add the selected moodboard images to this multi-view set"""

    bl_idname = "mixie.moodboard_add_selected_views"
    bl_label = "Add Selected"
    bl_description = (
        "Add every selected moodboard image to the multi-view set, giving "
        "each the next unused camera angle. Adjust any angle afterwards with "
        "its dropdown"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        main_image = _input_image(context)
        group_id = get_active_group(scene)

        images = eligible_selected_images(scene, group_id, main_image)
        if not images:
            self.report(
                {"WARNING"},
                "Select moodboard images that are not already views",
            )
            return {"CANCELLED"}

        capacity = remaining_capacity(scene, group_id) if group_id \
            else TURNAROUND_MAX_COMPANIONS
        if capacity <= 0:
            self.report(
                {"WARNING"},
                f"The set already holds {TURNAROUND_MAX_COMPANIONS} views",
            )
            return {"CANCELLED"}

        existing = bool(group_id)
        group_id = _ensure_group(scene)
        attached, skipped = add_images_as_views(
            scene, group_id, images, _model_slug(scene))
        if not attached:
            if not existing:
                # Do not leave the tab pointing at a set that never happened.
                set_active_group(scene, "")
            self.report({"WARNING"}, "No free camera angles left")
            return {"CANCELLED"}

        if skipped:
            # Say so rather than silently binning them — the next step is a
            # multi-minute, credit-charged job built from fewer views than
            # the user believes they supplied.
            self.report(
                {"WARNING"},
                f"{skipped} image(s) not added — the set is limited to "
                f"{TURNAROUND_MAX_COMPANIONS} views",
            )
        _redraw_all()
        self.report(
            {"INFO"},
            f"Added {len(attached)} view(s): {', '.join(attached)}",
        )
        return {"FINISHED"}


class MIXIE_OT_moodboard_add_turnaround_view(Operator):
    """Add an image file to this multi-view set"""

    bl_idname = "mixie.moodboard_add_turnaround_view"
    bl_label = "Add View From File"
    bl_description = (
        "Load an image file and add it to the multi-view set as the next "
        "unused camera angle. It is sent alongside the input image as one "
        "multi-view generation"
    )
    bl_options = {"REGISTER", "UNDO"}

    # Empty when the Model Gen tab has no set yet — one is minted on the fly
    # so a multi-view job can be assembled entirely by hand.
    group_id: bpy.props.StringProperty(default="")

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
        scene = context.scene
        group_id = self.group_id.strip() or _ensure_group(scene)
        if remaining_capacity(scene, group_id) <= 0:
            self.report(
                {"WARNING"},
                f"The set already holds {TURNAROUND_MAX_COMPANIONS} views",
            )
            return {"CANCELLED"}

        view_type = next_free_view_type(
            scene, group_id, allowed=allowed_view_types(_model_slug(scene)))
        if not view_type:
            self.report({"WARNING"}, "No free camera angles left")
            return {"CANCELLED"}

        image = self._load(context)
        if image is None:
            return {"CANCELLED"}
        if attach_image(scene, group_id, image, view_type) is None:
            self.report({"ERROR"}, "Could not add the image to the moodboard")
            return {"CANCELLED"}

        set_active_group(scene, group_id)
        mark_file_select_executed(self)
        _redraw_all()
        self.report({"INFO"}, f"Added '{image.name}' as the {view_type} view")
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


class MIXIE_OT_moodboard_promote_turnaround_view(Operator):
    """Use this view as the input image instead"""

    bl_idname = "mixie.moodboard_promote_turnaround_view"
    bl_label = "Use As Input Image"
    bl_description = (
        "Make this view the input image the model is built from. It leaves "
        "the multi-view set — the vendor has no angle for a front view — and "
        "the previous input image becomes an ordinary moodboard image"
    )
    bl_options = {"REGISTER", "UNDO"}

    group_id: bpy.props.StringProperty(default="")
    image_name: bpy.props.StringProperty(default="")

    def execute(self, context):
        scene = context.scene
        image = bpy.data.images.get(self.image_name.strip())
        if image is None:
            self.report({"WARNING"}, "View image not found")
            return {"CANCELLED"}

        group_id = self.group_id.strip()
        # keep_s3_key: the key is a valid upload of these exact pixels, so
        # promoting a detected crop still submits by key rather than
        # re-encoding the image.
        if group_id and not detach_image(
                scene, group_id, image, keep_s3_key=True):
            self.report({"WARNING"}, "View is not part of this set")
            return {"CANCELLED"}

        set_tab_input_image(scene, image)
        _redraw_all()
        self.report({"INFO"}, f"'{image.name}' is now the input image")
        return {"FINISHED"}


class MIXIE_OT_moodboard_clear_turnaround(Operator):
    """Clear the multi-view set so the input image generates on its own"""

    bl_idname = "mixie.moodboard_clear_turnaround"
    bl_label = "Clear Views"
    bl_description = (
        "Empty the multi-view set. The images stay on the moodboard; the tab "
        "goes back to generating from its input image alone"
    )
    bl_options = {"REGISTER", "UNDO"}

    group_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        group_id = self.group_id.strip() or get_active_group(context.scene)
        if not group_id:
            self.report({'WARNING'}, "No multi-view set to clear")
            return {'CANCELLED'}
        cleared = clear_group(context.scene, group_id)
        set_active_group(context.scene, "")
        if not cleared:
            self.report({'WARNING'}, "Multi-view set not found")
            return {'CANCELLED'}
        _redraw_all()
        self.report({'INFO'}, f"Cleared {cleared} view(s)")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_add_selected_views,
    MIXIE_OT_moodboard_add_turnaround_view,
    MIXIE_OT_moodboard_remove_turnaround_view,
    MIXIE_OT_moodboard_promote_turnaround_view,
    MIXIE_OT_moodboard_clear_turnaround,
)
