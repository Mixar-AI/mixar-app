# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lookdev360 PBR job queue: concrete Job + enqueue helpers.

Wires the generic ``FeatureQueue`` framework to the Lookdev360 PBR
generation service. All params are snapshotted at enqueue time.
"""

import base64 as _b64
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.job_queue_service import (
    get_job_queue_service,
)
from mixar.modules.common.job_queue import Job, get_queue
from mixar.modules.common.job_queue.core.job import FAILED_BACKEND_STATUSES
from mixar.modules.common.job_queue.constants import FEATURE_LOOKDEV360
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class Lookdev360Job(Job):
    """Concrete Job for Lookdev360 PBR texture generation (sync type)."""

    # Submission payload
    prompt: str = ""
    mesh_bytes_b64: str = ""
    mesh_filename: str = "model.obj"
    resolution: Optional[int] = None
    style_image_bytes_b64: Optional[str] = None
    reference_image_bytes_b64: Optional[str] = None

    # Context (for applying result + cleanup)
    stored_objects: List[str] = field(default_factory=list)
    stored_obj_path: str = ""

    # Internal state
    _texture_urls: Dict[str, str] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_job_queue_service()
        payload = {
            "prompt": self.prompt,
            "mesh_file_bytes_b64": self.mesh_bytes_b64,
            "mesh_filename": self.mesh_filename,
        }
        if self.resolution:
            payload["params"] = {"resolution": self.resolution}
        if self.style_image_bytes_b64:
            payload["style_ref_image_bytes_b64"] = self.style_image_bytes_b64
        if self.reference_image_bytes_b64:
            payload["reference_image_bytes_b64"] = self.reference_image_bytes_b64

        service.enqueue(
            job_type="pbr_gen",
            model="hunyuan-pbr",
            payload=payload,
            on_success=on_success,
            on_error=on_error,
            timeout=1200.0,
        )

    def poll(self, on_success, on_error) -> None:
        service = get_job_queue_service()
        service.get_job_status(
            self.backend_job_id,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            inner = {}

        self.backend_job_id = inner.get("job_id", "") or ""
        status = inner.get("status", "")
        result = inner.get("result") or {}

        if status == "DONE" and isinstance(result, dict):
            self._extract_texture_urls(result)

        if not self.backend_job_id and not self._texture_urls:
            raise ValueError("Enqueue response missing job_id")

        # Release large payload memory after successful submission
        self.mesh_bytes_b64 = ""
        self.style_image_bytes_b64 = None
        self.reference_image_bytes_b64 = None

    def should_skip_poll(self) -> bool:
        return bool(self._texture_urls)

    def parse_poll_response(self, response):
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            return ("WAIT", [])

        status = inner.get("status", "")
        self.backend_status = status

        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            if isinstance(result, dict):
                self._extract_texture_urls(result)
            return ("DONE", [])
        if status in FAILED_BACKEND_STATUSES:
            self.error = inner.get("error", "PBR generation failed")
            self.user_message = inner.get("user_message", "") or "PBR generation failed"
            return ("FAIL", [])
        return ("WAIT", [])

    def handle_result(self, result_files, on_done, on_error):
        """Download textures in bg thread, apply as fill layers on main thread."""
        if not self._texture_urls.get("basecolor"):
            on_error("Missing BaseColor texture URL in server response")
            return True

        urls = dict(self._texture_urls)
        stored_objects = list(self.stored_objects)
        stored_obj_path = self.stored_obj_path

        def _bg_download():
            try:
                from mixar.modules.moodboard.core.lookdev360_utils import (
                    download_texture_from_url,
                )

                timestamp = int(time.time())
                try:
                    albedo_img = download_texture_from_url(
                        urls["basecolor"], f"pbr_basecolor_{timestamp}"
                    )
                except Exception as e:
                    err = f"Failed to download BaseColor texture: {e}"

                    def _fail():
                        on_error(err)
                        return None

                    bpy.app.timers.register(_fail, first_interval=0.0)
                    return

                roughness_img = metallic_img = normal_img = None
                if urls.get("roughness"):
                    try:
                        roughness_img = download_texture_from_url(
                            urls["roughness"], f"pbr_roughness_{timestamp}"
                        )
                    except Exception as e:
                        logger.warning("Failed to download Roughness: %s", e)
                if urls.get("metallic"):
                    try:
                        metallic_img = download_texture_from_url(
                            urls["metallic"], f"pbr_metallic_{timestamp}"
                        )
                    except Exception as e:
                        logger.warning("Failed to download Metallic: %s", e)
                if urls.get("normal"):
                    try:
                        normal_img = download_texture_from_url(
                            urls["normal"], f"pbr_normal_{timestamp}"
                        )
                    except Exception as e:
                        logger.warning("Failed to download Normal: %s", e)

                def _apply():
                    _apply_textures(
                        stored_objects, albedo_img, roughness_img,
                        metallic_img, normal_img, timestamp,
                        stored_obj_path, on_done, on_error,
                    )
                    return None

                bpy.app.timers.register(_apply, first_interval=0.0)
            except Exception as e:
                err = f"Unexpected error during texture download: {e}"
                logger.error("[Lookdev360] %s", err)

                def _fail_outer():
                    on_error(err)
                    return None

                bpy.app.timers.register(_fail_outer, first_interval=0.0)

        threading.Thread(target=_bg_download, daemon=True).start()
        return True

    def get_poll_interval(self):
        return 3.0

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _extract_texture_urls(self, result: dict) -> None:
        """Extract texture URLs from API response data."""
        data = result
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        if "result" in data and isinstance(data["result"], dict):
            data = data["result"]

        if "textures" in data and isinstance(data["textures"], list):
            for tex in data["textures"]:
                if not isinstance(tex, dict):
                    continue
                tex_type = tex.get("texture_type", "").lower()
                url = tex.get("url", "")
                if url and tex_type in ("basecolor", "roughness", "metallic", "normal"):
                    self._texture_urls[tex_type] = url


def _apply_textures(
    stored_objects, albedo_img, roughness_img, metallic_img, normal_img,
    timestamp, stored_obj_path, on_done, on_error,
):
    """Apply downloaded textures as fill layers in the paint module."""
    from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node
    from mixar.modules.moodboard.core.lookdev360_paint_integration import (
        add_lookdev360_fill_layer,
    )

    layer_name = f"PBR_{timestamp}"
    applied_count = 0

    for obj_name in stored_objects:
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            continue

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        node = get_active_mpaint_node(obj)
        if not node or not node.node_tree:
            logger.warning("No MPaint node for '%s', skipping", obj_name)
            continue

        group_tree = node.node_tree
        mp = group_tree.mp

        layer = add_lookdev360_fill_layer(
            mp=mp,
            group_tree=group_tree,
            albedo_img=albedo_img,
            roughness_img=roughness_img,
            metallic_img=metallic_img,
            normal_img=normal_img,
            layer_name=layer_name,
        )
        if layer:
            applied_count += 1

    if applied_count == 0:
        on_error("Failed to apply textures to any object")
        return

    # Set scene flags so the "Restore Materials" button appears in the sidebar
    # and the restore operator knows which layer to remove.
    try:
        scene = bpy.context.scene
        if hasattr(scene, 'mixie_lookdev360_has_applied'):
            scene.mixie_lookdev360_has_applied = True
        if hasattr(scene, 'mixie_lookdev360_layer_name'):
            scene.mixie_lookdev360_layer_name = layer_name
        # Also update tab properties
        if hasattr(scene, 'mixie_moodboard_sidebar') and scene.mixie_moodboard_sidebar:
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_lookdev360'):
                props = sidebar.tab_lookdev360
                if hasattr(props, 'has_applied_materials'):
                    props.has_applied_materials = True
                if hasattr(props, 'layer_name'):
                    props.layer_name = layer_name
    except Exception:
        pass

    bpy.ops.file.pack_all()

    # Clean up temp OBJ
    try:
        if stored_obj_path and os.path.exists(stored_obj_path):
            os.unlink(stored_obj_path)
    except OSError:
        pass

    bpy.ops.ed.undo_push(message="Lookdev 360: Apply PBR Textures")
    on_done(", ".join(stored_objects))


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def enqueue_lookdev360_job(
    *,
    prompt: str,
    mesh_bytes_b64: str,
    mesh_filename: str = "model.obj",
    resolution: Optional[int] = None,
    style_image_bytes_b64: Optional[str] = None,
    reference_image_bytes_b64: Optional[str] = None,
    stored_objects: Optional[List[str]] = None,
    stored_obj_path: str = "",
) -> Optional[Lookdev360Job]:
    """Build a ``Lookdev360Job`` and submit it to the queue."""
    job = Lookdev360Job(
        feature_key=FEATURE_LOOKDEV360,
        label=f"Lookdev360: {prompt[:40]}",
        prompt=prompt,
        mesh_bytes_b64=mesh_bytes_b64,
        mesh_filename=mesh_filename,
        resolution=resolution,
        style_image_bytes_b64=style_image_bytes_b64,
        reference_image_bytes_b64=reference_image_bytes_b64,
        stored_objects=stored_objects or [],
        stored_obj_path=stored_obj_path,
    )
    queue = _get_lookdev360_queue()
    if not queue.submit(job):
        logger.warning("[Lookdev360] duplicate job rejected: %s", job.label)
        return None
    return job


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------


_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Sync lookdev360 progress bar to queue activity."""
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_generating = bool(getattr(scene, "mixie_lookdev360_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_lookdev360_is_generating = True
            if hasattr(scene, "mixie_lookdev360_error"):
                scene.mixie_lookdev360_error = ""
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_generating:
        try:
            scene.mixie_lookdev360_is_generating = False
        except (AttributeError, TypeError):
            pass

        # Redraw MIXIE sidebar so applied textures / error state are visible
        try:
            for area in bpy.context.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
        except Exception:
            pass


def _get_lookdev360_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_LOOKDEV360)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
