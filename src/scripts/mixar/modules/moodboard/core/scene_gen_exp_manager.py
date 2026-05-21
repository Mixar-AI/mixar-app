# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Gen Experimental Manager — label extraction via full scene reconstruction.

Submits an image with ``generate_mesh=False, labels_only=False`` so the
backend runs the full scene-reconstruction pipeline (Phase 1 GPU stages +
Phase 2 object parsing) but skips 3D mesh generation.  The plugin polls
until Phase 2 completes, then extracts just the object *labels* from the
``objects`` array and presents them in the UI for the user to select which
ones to use for per-object image generation.
"""

import re
import threading
import uuid
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

from ...common.api.services.scene_recon_service import get_scene_recon_service
from ...common.api.response import APIResponse

logger = get_logger(__name__)


POLL_INTERVAL = 1.5
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}

# Maximum number of concurrent imagegen requests to avoid backend rate limiting.
_MAX_CONCURRENT_IMAGEGEN = 20

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
        self._job_id: Optional[str] = None
        self._polling: bool = False
        # Concurrency-limited batching (Task 1)
        self._pending_targets: list[int] = []
        self._active_count: int = 0
        self._imagegen_service = None
        self._imagegen_params: dict = {}
        self._imagegen_image_bytes: bytes = b""
        # Grid layout positions (Task 3)
        self._grid_positions: dict[int, tuple[float, float]] = {}

    @property
    def is_processing(self) -> bool:
        return self._job_id is not None

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def submit_job(self, image_bytes: bytes, min_mask_pixels: int = 2000) -> bool:
        """Submit a labels job. Returns False if already running."""
        if self._job_id is not None:
            logger.warning("[SceneGenExp] Already has an active job")
            return False

        self._set_processing(True)
        self._reset_tab_state()

        def submit_api_call():
            try:
                service = get_scene_recon_service()
                response = service.submit_job(
                    image_bytes=image_bytes,
                    filename="scene.png",
                    min_mask_pixels=min_mask_pixels,
                    generate_mesh=False,
                    mesh_postprocess=False,
                    texture_baking=False,
                    vertex_color=False,
                    labels_only=False,
                )

                def handle():
                    self._handle_submit_response(response)
                    return None

                bpy.app.timers.register(handle, first_interval=0.0)
            except Exception as e:
                error_msg = str(e)

                def report():
                    self._set_error(error_msg)
                    return None

                bpy.app.timers.register(report, first_interval=0.0)

        threading.Thread(target=submit_api_call, daemon=True).start()
        logger.debug("[SceneGenExp] Submitting labels job...")
        return True

    def _handle_submit_response(self, response: APIResponse):
        if not response.success:
            self._set_error(response.message or "Label extraction failed")
            return

        data = response.data or {}
        inner = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        job_id = inner.get("job_id") or data.get("job_id")

        if not job_id:
            self._set_error("No job_id in response")
            return

        self._job_id = job_id
        self._write_tab(stage_detail="Queued...")
        self._start_polling()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _start_polling(self):
        self._polling = True

        def poll_timer():
            if not self._polling or not self._job_id:
                return None

            job_id = self._job_id

            def poll_api():
                try:
                    service = get_scene_recon_service()
                    response = service.get_job_status(job_id)

                    def handle():
                        self._handle_poll_response(response)
                        return None

                    bpy.app.timers.register(handle, first_interval=0.0)
                except Exception as e:
                    error_msg = str(e)

                    def report():
                        self._set_error(error_msg)
                        return None

                    bpy.app.timers.register(report, first_interval=0.0)

            threading.Thread(target=poll_api, daemon=True).start()
            return POLL_INTERVAL if self._polling else None

        bpy.app.timers.register(poll_timer, first_interval=POLL_INTERVAL)

    def _handle_poll_response(self, response: APIResponse):
        if not response.success:
            self._set_error(response.message or "Poll failed")
            return

        data = response.data or {}
        inner = data.get("data", {}) if isinstance(data.get("data"), dict) else data

        # Detect Phase 2 by the presence of "phase" key — the backend
        # auto-transitions from Phase 1 to Phase 2 once GPU stages finish.
        phase = inner.get("phase")
        if phase:
            self._handle_phase2_poll(inner)
        else:
            self._handle_phase1_poll(inner)

    # ------------------------------------------------------------------
    # Phase 1 — GPU stages (segmentation, VLM, etc.)
    # ------------------------------------------------------------------

    def _handle_phase1_poll(self, inner: dict):
        """Handle Phase 1 status — GPU server processing stages."""
        status = str(inner.get("status", "")).lower()
        stage_name = inner.get("stage_name", "") or ""
        stage_detail = inner.get("stage_detail", "") or ""

        self._write_tab(
            stage_detail=(
                stage_name
                + (" — " if stage_name and stage_detail else "")
                + stage_detail
            ) or "Processing..."
        )

        if status in TERMINAL_STATUSES:
            if status != "completed":
                self._polling = False
                error = inner.get("error") or f"Job {status}"
                self._set_error(error)
            # Phase 1 "completed" → backend auto-transitions to Phase 2;
            # the next poll will contain the "phase" key.

    # ------------------------------------------------------------------
    # Phase 2 — object parsing & (skipped) mesh generation
    # ------------------------------------------------------------------

    def _handle_phase2_poll(self, data: dict):
        """Handle Phase 2 status — extract labels when complete."""
        phase = data.get("phase", "")
        job_status = data.get("status", "")
        total = data.get("total_objects", 0)
        completed = data.get("completed_objects", 0)
        objects = data.get("objects", [])
        error = data.get("error")

        # Progress UI updates
        if phase == "downloading_npz":
            self._write_tab(stage_detail="Downloading scene data...")
        elif phase == "parsing":
            self._write_tab(stage_detail="Parsing scene...")
        elif phase == "model_generation":
            self._write_tab(
                stage_detail=f"Detecting objects ({completed}/{total})..."
            )
        elif phase == "completed":
            self._polling = False
            self._store_objects_from_scene_recon(objects)
            self._finish_job(success=True)
            return
        elif phase == "failed":
            self._polling = False
            # The backend may fail during GLB upload (generate_mesh=false)
            # but still have extracted labels + spatial data — recover them.
            if objects:
                logger.warning(
                    "[SceneGenExp] Phase failed (%s) but %d objects available, recovering labels",
                    error, len(objects),
                )
                self._store_objects_from_scene_recon(objects)
                self._finish_job(success=True)
            else:
                self._set_error(error or "Scene analysis failed")
            return

        # Also check job-level terminal status
        if job_status in TERMINAL_STATUSES and phase not in ("completed", "failed"):
            self._polling = False
            if job_status == "failed":
                self._set_error(error or "Job failed")
            elif objects:
                # Terminal but not phase-completed — still extract what we have
                self._store_objects_from_scene_recon(objects)
                self._finish_job(success=True)
            else:
                self._set_error("No objects detected")

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
        """
        Fire N concurrency-limited image generation requests, one per
        *selected* object (max ``_MAX_CONCURRENT_IMAGEGEN`` in-flight).

        Returns (success, message). On success, per-object state is updated
        as each callback arrives; on failure (e.g. nothing selected), returns
        (False, reason).
        """
        tab = self._get_tab()
        if tab is None:
            return False, "Sidebar properties not found"

        if tab.gen_in_progress:
            return False, "Image generation already in progress"

        # Collect target object indices (still-valid references via index).
        targets = [i for i, obj in enumerate(tab.objects) if obj.selected]
        if not targets:
            return False, "No objects selected"

        try:
            from ...common.api.services.imagegen_service import get_imagegen_service
        except ImportError as e:
            return False, f"ImageGen service unavailable: {e}"

        service = get_imagegen_service()

        # Reset per-object state for the targets and initialize counters.
        tab.gen_total_count = len(targets)
        tab.gen_completed_count = 0
        tab.gen_failed_count = 0
        tab.gen_in_progress = True
        for i in targets:
            obj = tab.objects[i]
            obj.gen_status = "generating"
            obj.gen_error = ""
        self._tag_redraw()

        # --- Task 3: Compute grid positions ---
        self._grid_positions = self._compute_grid_positions(targets)

        # --- Task 1: Store params for the pump pattern ---
        self._imagegen_service = service
        self._imagegen_params = {
            "model": model,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        self._imagegen_image_bytes = image_bytes
        self._pending_targets = list(targets)
        self._active_count = 0

        logger.info(
            "[SceneGenExp] Queued %d image generation requests "
            "(model=%s, aspect=%s, resolution=%s, max_concurrent=%d)",
            len(targets), model, aspect_ratio, resolution, _MAX_CONCURRENT_IMAGEGEN,
        )

        # Start pumping
        self._pump_imagegen()

        return True, ""

    # Scale for generated grid images (relative to MOODBOARD_IMAGE_BASE_SIZE)
    _GRID_IMAGE_SCALE = 0.5
    # Gap between grid images in pixels
    _GRID_GAP = 30.0

    def _compute_grid_positions(self, targets: list[int]) -> dict[int, tuple[float, float]]:
        """Compute grid (x, y) positions for each target index.

        Places images in a grid below the currently selected moodboard image.
        Falls back to viewport center if no image is selected.
        """
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
                    # Compute display size
                    aspect = iw / ih
                    disp_w = MOODBOARD_IMAGE_BASE_SIZE * ref_scale * aspect
                    disp_h = MOODBOARD_IMAGE_BASE_SIZE * ref_scale
                    ref_cx = ref_x + disp_w / 2
                    # Small gap below the reference image
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

        # Grid starts horizontally centered relative to ref_cx
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

    def _pump_imagegen(self):
        """Start queued imagegen requests up to the concurrency limit."""
        tab = self._get_tab()
        if tab is None:
            return

        while (
            self._active_count < _MAX_CONCURRENT_IMAGEGEN
            and self._pending_targets
        ):
            i = self._pending_targets.pop(0)
            if i < 0 or i >= len(tab.objects):
                continue
            obj = tab.objects[i]
            label = str(obj.label or "object")
            prompt = _IMAGEGEN_PROMPT_TEMPLATE.format(object_label=label)
            self._active_count += 1
            self._fire_single_imagegen(
                service=self._imagegen_service,
                prompt=prompt,
                label=label,
                object_index=i,
                image_bytes=self._imagegen_image_bytes,
                **self._imagegen_params,
            )

    def _fire_single_imagegen(
        self,
        service,
        prompt: str,
        label: str,
        object_index: int,
        model: str,
        aspect_ratio: str,
        resolution: str,
        image_bytes: bytes,
    ):
        """Fire a single async imagegen request and wire up callbacks."""

        def on_success(response: APIResponse):
            try:
                image_url = self._extract_image_url(response)
            except Exception as e:
                logger.error(
                    "[SceneGenExp] Failed to parse imagegen response for '%s': %s",
                    label, e,
                )
                image_url = None

            error_msg = None
            if image_url is None:
                if response is None or not response.success:
                    error_msg = (
                        (response.message if response else None)
                        or "Image generation failed"
                    )
                else:
                    error_msg = "No image URL in response"

            def apply():
                self._handle_imagegen_result(
                    object_index=object_index,
                    label=label,
                    image_url=image_url,
                    error_msg=error_msg,
                )
                return None

            bpy.app.timers.register(apply, first_interval=0.0)

        def on_error(error):
            err_str = str(error) if error else "Unknown error"
            logger.error(
                "[SceneGenExp] ImageGen request error for '%s': %s", label, err_str
            )

            def apply():
                self._handle_imagegen_result(
                    object_index=object_index,
                    label=label,
                    image_url=None,
                    error_msg=err_str,
                )
                return None

            bpy.app.timers.register(apply, first_interval=0.0)

        try:
            service.generate_async(
                prompt=prompt,
                model=model,
                style="none",
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                number_of_images=1,
                reference_images=[image_bytes],
                on_success=on_success,
                on_error=on_error,
            )
        except Exception as e:
            err_str = str(e)
            logger.error(
                "[SceneGenExp] Failed to fire imagegen for '%s': %s", label, err_str
            )

            def apply():
                self._handle_imagegen_result(
                    object_index=object_index,
                    label=label,
                    image_url=None,
                    error_msg=err_str,
                )
                return None

            bpy.app.timers.register(apply, first_interval=0.0)

    @staticmethod
    def _extract_image_url(response: APIResponse) -> Optional[str]:
        """Pull the first generated image URL out of an imagegen response."""
        if response is None or not response.success:
            return None
        data = response.data
        if not isinstance(data, dict):
            return None
        # Unwrap nested {"data": {...}} envelope if present
        if isinstance(data.get("data"), dict):
            data = data["data"]

        images_list = data.get("images") or []
        for item in images_list:
            if isinstance(item, dict) and item.get("url"):
                return item["url"]
            if isinstance(item, str):
                return item

        single = data.get("image_url")
        if isinstance(single, str) and single:
            return single
        return None

    @staticmethod
    def _sanitize_label(label: str) -> str:
        """Sanitize a label into a safe image name (underscored, no extension)."""
        import os
        name = (label or "object").strip() or "object"
        # Strip file extension if present
        name = os.path.splitext(name)[0]
        # Replace spaces and non-alphanumeric chars (except underscores) with underscores
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        # Collapse multiple underscores
        name = re.sub(r'_+', '_', name).strip('_')
        return name or "object"

    def _handle_imagegen_result(
        self,
        object_index: int,
        label: str,
        image_url: Optional[str],
        error_msg: Optional[str],
    ):
        """Main-thread handler: update per-object state + add to moodboard."""
        # Decrement active count and pump next request (Task 1)
        self._active_count = max(0, self._active_count - 1)

        tab = self._get_tab()
        if tab is None:
            return

        if object_index < 0 or object_index >= len(tab.objects):
            logger.warning(
                "[SceneGenExp] Object index %d out of range on imagegen callback",
                object_index,
            )
            self._pump_imagegen()
            return

        obj = tab.objects[object_index]

        if image_url and not error_msg:
            try:
                from mixar.modules.common.utils.image_utils import (
                    add_image_to_moodboard,
                    load_image_from_url,
                )
                # Task 2: sanitized naming
                safe_name = self._sanitize_label(label)
                img = load_image_from_url(image_url, safe_name)
                img.name = safe_name  # Blender auto-disambiguates duplicates

                # Task 3: grid position + scale
                px, py = self._grid_positions.get(object_index, (None, None))
                add_image_to_moodboard(
                    img, prompt=label,
                    position_x=px, position_y=py,
                    scale=self._GRID_IMAGE_SCALE,
                )

                # Stamp chain_id on the newly added moodboard image
                if obj.chain_id:
                    try:
                        scene = bpy.context.scene
                        for mb_item in reversed(scene.mixie_moodboard_images):
                            if mb_item.image == img:
                                mb_item.chain_id = obj.chain_id
                                break
                    except Exception as e:
                        logger.debug("[SceneGenExp] Failed to stamp chain_id: %s", e)

                obj.gen_status = "completed"
                obj.gen_error = ""
                tab.gen_completed_count += 1
                logger.info(
                    "[SceneGenExp] Added generated image '%s' for object '%s'",
                    img.name, label,
                )
            except Exception as e:
                obj.gen_status = "failed"
                obj.gen_error = f"Download/add failed: {e}"
                tab.gen_failed_count += 1
                logger.error(
                    "[SceneGenExp] Failed to add image for '%s': %s", label, e
                )
        else:
            obj.gen_status = "failed"
            obj.gen_error = error_msg or "Unknown error"
            tab.gen_failed_count += 1

        # Flip gen_in_progress off when everyone is done
        if (tab.gen_completed_count + tab.gen_failed_count) >= tab.gen_total_count:
            tab.gen_in_progress = False
            self._grid_positions.clear()
            logger.info(
                "[SceneGenExp] Image generation batch finished: %d ok, %d failed",
                tab.gen_completed_count, tab.gen_failed_count,
            )

        self._tag_redraw()

        # Pump next queued request (Task 1)
        self._pump_imagegen()

    # ------------------------------------------------------------------
    # Result storage
    # ------------------------------------------------------------------

    def _store_objects_from_scene_recon(self, objects: list):
        """Extract labels and spatial metadata from the Phase 2 ``objects`` array.

        Phase 2 objects have ``{index, label, status, center, dimensions,
        rotation, scale, ...}``.  Labels are used for per-object image
        generation; spatial data is stored for future positioning.
        """
        tab = self._get_tab()
        if tab is None:
            return
        tab.objects.clear()
        for obj in objects:
            label = str(obj.get("label", "")).strip()
            if not label:
                label = f"object_{obj.get('index', len(tab.objects))}"
            item = tab.objects.add()
            item.label = label
            item.chain_id = str(uuid.uuid4())

            # Store 3D spatial metadata when available
            center = obj.get("center")
            if center and len(center) >= 3:
                item.center = (float(center[0]), float(center[1]), float(center[2]))
            dims = obj.get("dimensions")
            if dims and len(dims) >= 3:
                item.dimensions = (float(dims[0]), float(dims[1]), float(dims[2]))
            rot = obj.get("rotation")
            if rot and len(rot) >= 4:
                item.rotation = (float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3]))
            scale = obj.get("scale")
            if scale is not None:
                item.obj_scale = float(scale)

        tab.has_result = True
        logger.info(
            "[SceneGenExp] Extracted %d labels from scene reconstruction",
            len(tab.objects),
        )

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
        # Reset Step 2 batch state as well — new labels wipe old image-gen status
        tab.gen_in_progress = False
        tab.gen_total_count = 0
        tab.gen_completed_count = 0
        tab.gen_failed_count = 0

    def _write_tab(self, stage_detail: str = "", error_text: Optional[str] = None):
        tab = self._get_tab()
        if tab is None:
            return
        tab.stage_detail = stage_detail
        if error_text is not None:
            tab.error_text = error_text
        self._tag_redraw()

    def _set_processing(self, processing: bool):
        try:
            scene = bpy.context.scene
            if scene and hasattr(scene, 'mixie_scene_gen_exp_is_processing'):
                scene.mixie_scene_gen_exp_is_processing = processing
        except Exception:
            pass
        self._tag_redraw()

    def _set_error(self, error_msg: str):
        logger.error("[SceneGenExp] %s", error_msg)
        tab = self._get_tab()
        if tab is not None:
            tab.error_text = error_msg
            tab.stage_detail = ""
        self._finish_job(success=False)

    def _finish_job(self, success: bool = True):
        self._job_id = None
        self._polling = False
        self._set_processing(False)
        self._tag_redraw()

    def _tag_redraw(self):
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass

    def clear_all(self) -> None:
        """Stop polling and release captured state. Called on addon teardown."""
        self._polling = False
        self._job_id = None
        self._pending_targets.clear()


# Singleton instance
_scene_gen_exp_manager: Optional[SceneGenExpManager] = None


def get_scene_gen_exp_manager() -> SceneGenExpManager:
    """Get or create the global Scene Gen Experimental manager."""
    global _scene_gen_exp_manager
    if _scene_gen_exp_manager is None:
        _scene_gen_exp_manager = SceneGenExpManager()
    return _scene_gen_exp_manager
