# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Magic Select tool: click an object on a Moodboard image to mask it.

One action, one wait. The service needs the image uploaded before it can
segment, but the user never sees that step: the tool activates instantly, the
upload runs in the background, and a click that lands before it finishes is
queued and runs the moment it lands (`core/magic_select_flow.py` owns that
choreography and is unit-tested). Progress is one pulsing marker at the
clicked point plus the workspace status line; terminal failures are toasts.
`Operator.report()` is deliberately absent from every callback: reports from
a timer never reach the screen (see `core/mask_tool_feedback.py`).
"""

import os
import tempfile

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import magic_select_flow as flow_mod
from ...core.canvas_context import redraw_moodboard_canvases
from ...core.magic_select_flow import MagicSelectFlow
from ...core.mask_tool_context import mouse_to_image_coords
from ...core.mask_tool_feedback import clear_status, set_status, toast_failure
from ...core.media_utils import is_still_item
from ...core.scene_segment_manager import get_scene_segment_manager
from ...core.segment_overlay import recomposite_display_image

logger = get_logger(__name__)

#: Redraw cadence for the pulsing marker while a click is in flight.
MARKER_PULSE_INTERVAL = 1.0 / 15.0


def _mark_point(state, point) -> None:
    """Mirror the queued/in-flight click for the C++ marker painter."""
    if point is None:
        state.magic_select_has_point = False
        return
    state.magic_select_point_x, state.magic_select_point_y = point
    state.magic_select_has_point = True


class MIXIE_OT_moodboard_magic_select_tool(Operator):
    """Activate Magic Select - click on image to segment object with AI"""
    bl_idname = "mixie.moodboard_magic_select_tool"
    bl_label = "Magic Select Tool"
    bl_description = "Activate Magic Select - click on image to segment object with AI"
    bl_options = {'REGISTER', 'BLOCKING'}

    _target_image_index: int = -1
    _flow: MagicSelectFlow = None
    _pulse_running: bool = False

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_moodboard_images'):
            return False
        selected = [i for i, img in enumerate(context.scene.mixie_moodboard_images)
                    if img.selected and is_still_item(img)]
        return len(selected) == 1

    # -- lifecycle -------------------------------------------------------

    def invoke(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        # Preserve the shared legacy segmentation form selection
        from ..sidebar_ui_helpers import focus_segments_panel
        focus_segments_panel(context)

        selected_idx = next(
            (i for i, img in enumerate(scene.mixie_moodboard_images)
             if img.selected and is_still_item(img)),
            -1,
        )
        if selected_idx < 0:
            self.report({'WARNING'}, "No image selected")
            return {'CANCELLED'}

        img_item = scene.mixie_moodboard_images[selected_idx]
        manager = get_scene_segment_manager()

        state.active_tool = 'MAGIC_SELECT'
        state.target_image_index = selected_idx
        state.magic_select_pending = False
        _mark_point(state, None)
        self._target_image_index = selected_idx
        self._flow = MagicSelectFlow(upload_ready=manager.is_ready(img_item.image))

        # Warm the upload in the background; the user is never told to wait
        # for it. A click before it lands is queued, not swallowed.
        if not self._flow.upload == "ready":
            self._start_upload(img_item)

        set_status(self._flow.status_text())
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        if event.type == 'ESC':
            self._cleanup_state(state, context)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            img_rel = mouse_to_image_coords(context, event, state.target_image_index)
            if img_rel is None:
                # Click outside image - deactivate tool like ESC
                self._cleanup_state(state, context)
                return {'CANCELLED'}
            self._on_click(state, img_rel)
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def _cleanup_state(self, state, context):
        """Clean up tool state."""
        state.active_tool = 'NONE'
        state.target_image_index = -1
        state.magic_select_pending = False
        _mark_point(state, None)
        self._flow = None
        clear_status()
        if context.area:
            context.area.tag_redraw()

    # -- choreography ----------------------------------------------------

    def _on_click(self, state, point):
        flow = self._flow
        action = flow.click(*point)
        _mark_point(state, point)
        if action == flow_mod.SEGMENT:
            self._perform_segmentation(state)
        elif action == flow_mod.UPLOAD:
            self._start_upload(self._img_item())
        self._sync(state)

    def _sync(self, state):
        """Mirror the flow onto the props the painter and QA read."""
        if self._flow is None:
            return
        state.magic_select_pending = self._flow.pending
        set_status(self._flow.status_text())
        if self._flow.pending:
            self._ensure_pulse()
        redraw_moodboard_canvases()

    def _img_item(self):
        return bpy.context.scene.mixie_moodboard_images[self._target_image_index]

    def _state(self):
        return bpy.context.scene.mixie_edit_tool_state

    def _start_upload(self, img_item):
        flow = self._flow
        flow.upload_started()

        def on_upload_complete(success, message):
            if self._flow is not flow:
                return  # tool exited while the upload was in flight
            state = self._state()
            action = flow.upload_done(success)
            if action == flow_mod.SEGMENT:
                self._perform_segmentation(state)
            elif not success:
                _mark_point(state, None)
                logger.error("[MagicSelect] Upload failed: %s", message)
                toast_failure(message, upload=True)
            self._sync(state)

        get_scene_segment_manager().queue_upload(
            img_item.image, img_item=img_item, on_complete=on_upload_complete,
        )

    def _perform_segmentation(self, state):
        """Send the queued point to Scene Segment (SAM3)."""
        flow = self._flow
        click_x, click_y = flow.segment_started()
        img_item = self._img_item()

        # API uses y=0 at top, Blender View2D uses y=0 at bottom; label 1=include
        points = [{"x": click_x, "y": 1.0 - click_y, "label": 1}]

        def on_complete(success: bool, mask_bytes, message: str):
            """Segmentation result (main thread, via the manager's timer)."""
            if self._flow is not flow:
                return
            state = self._state()
            created = bool(success and mask_bytes) and self._create_segment(state, mask_bytes)
            if not created:
                error_msg = message or "Unknown error"
                if error_msg == "expired":
                    logger.debug("[MagicSelect] Job expired, re-uploading and retrying...")
                    flow.upload_expired((click_x, click_y))
                    self._start_upload(img_item)
                    self._sync(state)
                    return
                if success:
                    error_msg = "The returned mask could not be read"
                logger.warning("[MagicSelect] Segmentation failed: %s", error_msg)
                toast_failure(error_msg)
            action = flow.segment_done(created)
            if action == flow_mod.SEGMENT:
                self._perform_segmentation(state)
            elif flow.point is None:
                _mark_point(state, None)
            self._sync(state)

        get_scene_segment_manager().request_segmentation(
            image=img_item.image, points=points, on_complete=on_complete,
        )

    def _ensure_pulse(self):
        """Redraw the marker at 15 fps while a click is in flight, then stop."""
        if self._pulse_running:
            return
        self._pulse_running = True

        def tick():
            flow = self._flow
            if flow is None or not flow.pending:
                self._pulse_running = False
                return None
            redraw_moodboard_canvases()
            return MARKER_PULSE_INTERVAL

        bpy.app.timers.register(tick, first_interval=MARKER_PULSE_INTERVAL)

    # -- result ----------------------------------------------------------

    def _create_segment(self, state, mask_bytes) -> bool:
        """Add the mask to the image's segments and recomposite. True on success."""
        scene = bpy.context.scene
        mask_temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='_mask.png', delete=False) as f:
                f.write(mask_bytes)
                mask_temp_path = f.name

            mask_img = bpy.data.images.load(mask_temp_path, check_existing=False)
            if mask_img.size[0] == 0 or mask_img.size[1] == 0:
                logger.error("[SceneSegment] Invalid mask dimensions")
                bpy.data.images.remove(mask_img)
                return False

            img_item = scene.mixie_moodboard_images[self._target_image_index]
            next_index = len(img_item.segments) + 1
            segment_name = f"Segment {next_index}"
            mask_img.name = f"{img_item.image.name}_{segment_name}_mask"
            mask_img.pack()

            segment = img_item.segments.add()
            segment.mask_image = mask_img
            segment.active = True
            segment.index = next_index
            segment.name = segment_name

            recomposite_display_image(img_item)
            from ...core.component_debug import add_sam3_mask_preview

            add_sam3_mask_preview(
                scene, self._target_image_index, mask_img, segment_name,
            )
            logger.debug("[SceneSegment] Added %s to image", segment_name)
            return True
        except Exception as e:
            logger.error("[SceneSegment] Failed to create segment: %s", e, exc_info=True)
            return False
        finally:
            if mask_temp_path:
                try:
                    os.unlink(mask_temp_path)
                except OSError:
                    pass


classes = (
    MIXIE_OT_moodboard_magic_select_tool,
)
