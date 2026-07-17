# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Gen Experimental Manager — label extraction via full scene reconstruction.

Submits an image with ``generate_mesh=False`` so the backend runs the full
scene-reconstruction pipeline but skips 3D mesh generation.  Once complete,
the extracted object *labels* are presented in the UI for the user to select
which ones to use for per-object image generation.

Both flows (label extraction + per-object imagegen) use the unified
FeatureQueue / job_queue_service system.
"""

import base64 as _b64
import re
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# Per-object image generation prompt. {object_label} is substituted per object.
_IMAGEGEN_PROMPT_TEMPLATE = (
    "Extract ONLY the {object_label} from this image and nothing else - "
    "do not include any other object, background element, or surrounding detail - "
    "strictly preserve the overall look of the {object_label} as it appears in "
    "the source image (same shape, proportions, colors, materials, and textures "
    "- do not restyle, redesign, or reinterpret it) - if the source image is "
    "blurry, low-resolution, or lacks fine detail, you may sharpen and add "
    "realistic missing details that are faithful to the object's identity and "
    "consistent with its visible form, but never change its design, style, or "
    "character - place it on a pure white background - delight the image - "
    "clearly visible - fit properly in the image"
)


class SceneGenExpManager:
    """Singleton manager for the Scene Gen Experimental labels job."""

    def __init__(self):
        # Grid layout positions (Task 3)
        self._grid_positions: dict[int, tuple[float, float]] = {}
        # Track imagegen jobs for batch progress
        self._imagegen_job_ids: list[str] = []

    # ------------------------------------------------------------------
    # Submit (Step 1: label extraction)
    # ------------------------------------------------------------------

    def submit_job(self, image_bytes: bytes, min_mask_pixels: int = 2000) -> bool:
        """Submit a labels extraction job via the unified queue.

        Returns False if already running.
        """
        try:
            scene = bpy.context.scene
            if getattr(scene, "mixie_scene_gen_exp_is_processing", False):
                logger.warning("[SceneGenExp] Already has an active job")
                return False
        except Exception:
            pass

        self._reset_tab_state()

        from .scene_gen_exp_labels_queue import enqueue_scene_gen_exp_labels_job

        job = enqueue_scene_gen_exp_labels_job(
            image_bytes=image_bytes,
            min_mask_pixels=min_mask_pixels,
            on_labels_ready=self._on_labels_ready,
            on_error=self._on_labels_error,
        )

        if not job:
            logger.warning("[SceneGenExp] Failed to enqueue labels job")
            return False

        logger.debug("[SceneGenExp] Enqueued labels job %s", job.id)
        return True

    def _on_labels_ready(self):
        """Called on main thread when labels have been extracted."""
        self._tag_redraw()

    def _on_labels_error(self, error_msg: str):
        """Called on main thread when label extraction fails."""
        logger.error("[SceneGenExp] %s", error_msg)
        tab = self._get_tab()
        if tab is not None:
            tab.error_text = error_msg
            tab.stage_detail = ""
        self._tag_redraw()

    # ------------------------------------------------------------------
    # Step 2: Batch image generation
    # ------------------------------------------------------------------

    def generate_object_images(
        self,
        image_bytes: bytes,
        model: str,
        aspect_ratio: str,
        resolution: str,
    ) -> tuple[bool, str]:
        """Enqueue one image generation job per selected object.

        Returns (success, message).
        """
        tab = self._get_tab()
        if tab is None:
            return False, "Sidebar properties not found"

        if tab.gen_in_progress:
            return False, "Image generation already in progress"

        targets = [i for i, obj in enumerate(tab.objects) if obj.selected]
        if not targets:
            return False, "No objects selected"

        from mixar.modules.common.job_queue import enqueue_generation
        from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN

        # Reset per-object state and batch counters
        tab.gen_total_count = len(targets)
        tab.gen_completed_count = 0
        tab.gen_failed_count = 0
        tab.gen_in_progress = True
        for i in targets:
            obj = tab.objects[i]
            obj.gen_status = "generating"
            obj.gen_error = ""
        self._tag_redraw()

        # Compute grid positions
        self._grid_positions = self._compute_grid_positions(targets)

        # Encode reference image once
        ref_b64 = [_b64.b64encode(image_bytes).decode()]

        # Enqueue one imagegen job per target object
        self._imagegen_job_ids.clear()
        for i in targets:
            obj = tab.objects[i]
            label = str(obj.label or "object")
            prompt = _IMAGEGEN_PROMPT_TEMPLATE.format(object_label=label)

            payload = {
                "prompt": prompt,
                "params": {
                    "style": "none",
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                    "number_of_images": 1,
                },
            }
            if ref_b64:
                payload["reference_images_b64"] = ref_b64

            # NOTE: No scene_flag/listener here — the imagegen queue
            # listener is already attached by imagegen_ops.py (bootstrap).
            # Per-object tracking is handled by _attach_imagegen_listener.
            job = enqueue_generation(
                kind="image",
                feature_key=FEATURE_IMAGEGEN,
                job_type="image_gen",
                model=model,
                payload=payload,
                label=f"ImageGen: {prompt[:40]}",
                display_label=prompt[:40],
                fail_message="Image generation failed",
                name_prefix="imagegen",
                prompt_text=prompt,
                undo_message="Generate Image",
            )

            if job:
                self._imagegen_job_ids.append(job.id)
                # Attach a completion listener for per-object tracking
                self._attach_imagegen_listener(job.id, i, label)
            else:
                obj.gen_status = "failed"
                obj.gen_error = "Failed to enqueue"
                tab.gen_failed_count += 1

        # If all enqueue attempts failed immediately
        if tab.gen_failed_count >= tab.gen_total_count:
            tab.gen_in_progress = False
            self._grid_positions.clear()
            return False, "All image generation jobs failed to enqueue"

        logger.info(
            "[SceneGenExp] Enqueued %d image generation jobs "
            "(model=%s, aspect=%s, resolution=%s)",
            len(self._imagegen_job_ids), model, aspect_ratio, resolution,
        )
        return True, ""

    def _attach_imagegen_listener(self, job_id: str, object_index: int, label: str):
        """Listen to the imagegen queue for a specific job's completion."""
        from mixar.modules.common.job_queue import get_queue, JobState, TERMINAL_STATES
        from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN

        queue = get_queue(FEATURE_IMAGEGEN)

        def on_change(q):
            job = None
            for j in q.snapshot():
                if j.id == job_id:
                    job = j
                    break
            if job is None or job.state not in TERMINAL_STATES:
                return

            # One-shot: remove listener once terminal
            try:
                q.remove_listener(on_change)
            except Exception:
                pass

            def apply():
                self._handle_imagegen_result(
                    object_index=object_index,
                    label=label,
                    job=job,
                )
                return None

            bpy.app.timers.register(apply, first_interval=0.0)

        queue.add_listener(on_change)

    # Scale for generated grid images (relative to MOODBOARD_IMAGE_BASE_SIZE)
    _GRID_IMAGE_SCALE = 0.5
    # Gap between grid images in pixels
    _GRID_GAP = 30.0

    def _compute_grid_positions(self, targets: list[int]) -> dict[int, tuple[float, float]]:
        """Compute grid (x, y) positions for each target index."""
        from ..constants import MOODBOARD_IMAGE_BASE_SIZE

        n = len(targets)
        if n == 0:
            return {}

        cols = min(n, 6)
        img_size = MOODBOARD_IMAGE_BASE_SIZE * self._GRID_IMAGE_SCALE
        cell = img_size + self._GRID_GAP

        # Find reference image position
        ref_cx, ref_bottom_y = 0.0, 0.0
        found_ref = False
        try:
            scene = bpy.context.scene
            for item in scene.mixie_moodboard_images:
                if item.selected and item.image:
                    ref_x = item.position_x
                    ref_y = item.position_y
                    ref_scale = item.scale
                    iw, ih = item.image.size[0], item.image.size[1]
                    if iw == 0 or ih == 0:
                        iw, ih = MOODBOARD_IMAGE_BASE_SIZE, MOODBOARD_IMAGE_BASE_SIZE
                    aspect = iw / ih
                    disp_w = MOODBOARD_IMAGE_BASE_SIZE * ref_scale * aspect
                    disp_h = MOODBOARD_IMAGE_BASE_SIZE * ref_scale
                    ref_cx = ref_x + disp_w / 2
                    ref_bottom_y = ref_y - disp_h - self._GRID_GAP
                    found_ref = True
                    break
        except Exception:
            pass

        if not found_ref:
            try:
                from mixar.modules.moodboard.core.moodboard_utils import (
                    get_moodboard_viewport_center,
                )
                ref_cx, ref_bottom_y = get_moodboard_viewport_center()
            except Exception:
                ref_cx, ref_bottom_y = 0.0, 0.0

        grid_width = cols * cell - self._GRID_GAP
        grid_start_x = ref_cx - grid_width / 2

        positions: dict[int, tuple[float, float]] = {}
        for idx_in_grid, obj_index in enumerate(targets):
            col = idx_in_grid % cols
            row = idx_in_grid // cols
            px = grid_start_x + col * cell
            py = ref_bottom_y - row * cell
            positions[obj_index] = (px, py)

        return positions

    @staticmethod
    def _sanitize_label(label: str) -> str:
        """Sanitize a label into a safe image name."""
        import os
        name = (label or "object").strip() or "object"
        name = os.path.splitext(name)[0]
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name).strip('_')
        return name or "object"

    def _handle_imagegen_result(self, object_index: int, label: str, job):
        """Main-thread handler: update per-object state from completed imagegen job."""
        from mixar.modules.common.job_queue import JobState

        tab = self._get_tab()
        if tab is None:
            return

        if object_index < 0 or object_index >= len(tab.objects):
            logger.warning(
                "[SceneGenExp] Object index %d out of range on imagegen callback",
                object_index,
            )
            return

        obj = tab.objects[object_index]

        if job.state == JobState.SUCCESS and job.imported_object_names:
            # The imagegen queue's handle_result already added image(s) to the
            # moodboard. We need to stamp chain_id + set position/scale.
            try:
                self._post_process_moodboard_image(obj, object_index, label)
                obj.gen_status = "completed"
                obj.gen_error = ""
                tab.gen_completed_count += 1
                logger.info(
                    "[SceneGenExp] Image generated for object '%s'", label,
                )
            except Exception as e:
                obj.gen_status = "failed"
                obj.gen_error = f"Post-processing failed: {e}"
                tab.gen_failed_count += 1
                logger.error(
                    "[SceneGenExp] Post-process failed for '%s': %s", label, e,
                )
        else:
            obj.gen_status = "failed"
            obj.gen_error = job.error or "Image generation failed"
            tab.gen_failed_count += 1

        # Check if batch is done
        if (tab.gen_completed_count + tab.gen_failed_count) >= tab.gen_total_count:
            tab.gen_in_progress = False
            self._grid_positions.clear()
            self._imagegen_job_ids.clear()
            logger.info(
                "[SceneGenExp] Image generation batch finished: %d ok, %d failed",
                tab.gen_completed_count, tab.gen_failed_count,
            )

        self._tag_redraw()

    def _post_process_moodboard_image(self, obj, object_index: int, label: str):
        """Stamp chain_id and reposition the most recently added moodboard image."""
        scene = bpy.context.scene
        # Find the most recent moodboard image (imagegen queue adds at the end)
        if not scene.mixie_moodboard_images:
            return
        mb_item = scene.mixie_moodboard_images[-1]

        # Stamp chain_id
        if obj.chain_id:
            mb_item.chain_id = obj.chain_id

        # Apply grid position + scale
        pos = self._grid_positions.get(object_index)
        if pos is not None:
            mb_item.position_x = pos[0]
            mb_item.position_y = pos[1]
        mb_item.scale = self._GRID_IMAGE_SCALE

        # Rename image to sanitized label
        if mb_item.image:
            safe_name = self._sanitize_label(label)
            mb_item.image.name = safe_name

    # ------------------------------------------------------------------
    # Tab state helpers
    # ------------------------------------------------------------------

    def _get_tab(self):
        try:
            scene = bpy.context.scene
            if not scene or not hasattr(scene, 'mixie_moodboard_sidebar'):
                return None
            sidebar = scene.mixie_moodboard_sidebar
            if not hasattr(sidebar, 'tab_scene_gen_exp'):
                return None
            return sidebar.tab_scene_gen_exp
        except Exception:
            return None

    def _reset_tab_state(self):
        tab = self._get_tab()
        if tab is None:
            return
        tab.error_text = ""
        tab.stage_detail = ""
        tab.has_result = False
        tab.objects.clear()
        tab.rename_allowed = True
        tab.gen_in_progress = False
        tab.gen_total_count = 0
        tab.gen_completed_count = 0
        tab.gen_failed_count = 0

    def _tag_redraw(self):
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass

    def clear_all(self) -> None:
        """Cancel active queue jobs and release state. Called on addon teardown."""
        self._imagegen_job_ids.clear()
        self._grid_positions.clear()


# Singleton instance
_scene_gen_exp_manager: Optional[SceneGenExpManager] = None


def get_scene_gen_exp_manager() -> SceneGenExpManager:
    """Get or create the global Scene Gen Experimental manager."""
    global _scene_gen_exp_manager
    if _scene_gen_exp_manager is None:
        _scene_gen_exp_manager = SceneGenExpManager()
    return _scene_gen_exp_manager
