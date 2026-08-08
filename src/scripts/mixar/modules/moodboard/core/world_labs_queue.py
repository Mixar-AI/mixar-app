# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""World Labs (Marble) world-generation queue: concrete Job + enqueue helper.

Genuinely-unique job (per CLAUDE.md): the backend returns a Gaussian-splat SPZ
+ a GLB collider, which we convert (SPZ -> 3DGS PLY) locally and import via the
bundled KIRI addon -- not a standard GLB import -- so it has its own queue file
with a custom ``handle_result``, modelled on ``lookdev360_queue``.
"""

import os
import tempfile
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.job_queue_service import (
    get_job_queue_service,
)
from mixar.modules.common.job_queue import Job, get_queue
from mixar.modules.common.job_queue.constants import FEATURE_WORLD_LABS
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue

logger = get_logger(__name__)

_SERVICE_KEY = "world_labs"

_DOWNLOAD_TIMEOUT = 300  # seconds


@dataclass
class WorldLabsJob(Job):
    """Concrete Job for World Labs world generation (async)."""

    # Submission payload
    mode: str = "text"            # "text" | "image"
    prompt: str = ""
    model: str = "marble-1.1"
    lod: str = "500k"
    image_bytes_b64: str = ""

    # Internal: capture the converted-asset URLs from the DONE result.
    _spz_url: str = ""
    _glb_url: str = ""
    _pano_url: str = ""
    _semantics: dict = field(default_factory=dict)
    _processing_started: bool = False

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        payload = {
            "mode": self.mode,
            "prompt": self.prompt,
            "lod": self.lod,
        }
        if self.mode == "image" and self.image_bytes_b64:
            payload["image_bytes_b64"] = self.image_bytes_b64
            # compress_for_service() returns JPEG bytes — keep the extension honest
            # so the S3 content-type and the vendor's content sniffing agree.
            payload["image_filename"] = "image.jpg"

        get_job_queue_service().enqueue(
            job_type=_SERVICE_KEY,
            model=self.model,
            payload=payload,
            idempotency_key=self.submit_idempotency_key,
            # A Marble world is a multi-minute, ~1.5k-vendor-credit job; a
            # failed submit must surface, never silently re-bill.
            max_retries=0,
            on_success=on_success,
            on_error=on_error,
            timeout=1800.0,
        )

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)
        # Release the (potentially large) base64 image after submission.
        self.image_bytes_b64 = ""

    def parse_poll_response(self, response):
        status, result_files = self._parse_standard_poll(
            response, fail_message="World generation failed",
        )
        if status == "DONE":
            for f in result_files or []:
                ftype = (f.get("type") or "").upper()
                if ftype == "SPZ":
                    self._spz_url = f.get("url", "")
                elif ftype == "GLB":
                    self._glb_url = f.get("url", "")
                elif ftype == "PANO":
                    self._pano_url = f.get("url", "")
            # World Labs scale metadata (sibling of result_files in the result).
            inner = self._unwrap_response(response)
            sem = (inner.get("result") or {}).get("semantics_metadata")
            if isinstance(sem, dict):
                self._semantics = sem
        return status, result_files

    def handle_result(self, result_files, on_done, on_error):
        """Download SPZ+GLB and convert+import on the main thread."""
        # Prefer cached URLs (set in parse_poll_response), but fall back to the
        # result_files passed in here so we don't depend on call ordering.
        if not self._spz_url:
            for f in result_files or []:
                ftype = (f.get("type") or "").upper()
                if ftype == "SPZ":
                    self._spz_url = f.get("url", "")
                elif ftype == "GLB":
                    self._glb_url = f.get("url", "")
                elif ftype == "PANO":
                    self._pano_url = f.get("url", "")

        if not self._spz_url:
            on_error("World generation result missing splat (SPZ) URL")
            return True

        spz_url, glb_url, pano_url, label = (
            self._spz_url, self._glb_url, self._pano_url, self.label,
        )
        semantics = dict(self._semantics)

        def _bg_download():
            ply_path = ""
            try:
                ply_path = _download_and_convert_spz(spz_url, label)
                # The collider is secondary — never fail the whole import if it
                # can't be fetched.
                glb_path = ""
                if glb_url:
                    try:
                        glb_path = _download_glb(glb_url)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[WorldLabs] collider GLB download failed: %s", e)
            except Exception as e:  # noqa: BLE001
                err = f"Failed to download/convert world: {e}"
                logger.error("[WorldLabs] %s", err)
                if ply_path and os.path.exists(ply_path):
                    try:
                        os.unlink(ply_path)
                    except OSError:
                        pass
                bpy.app.timers.register(
                    lambda: (on_error(err), None)[1], first_interval=0.0
                )
                return

            def _import():
                _import_on_main(
                    ply_path, glb_path, pano_url, label, semantics, on_done, on_error,
                )
                return None

            bpy.app.timers.register(_import, first_interval=0.0)

        threading.Thread(target=_bg_download, daemon=True).start()
        return True

    def get_poll_interval(self):
        return 5.0

    def release_resources(self) -> None:
        """Drop the large submit payload and result URLs once terminal."""
        self.image_bytes_b64 = ""
        self._spz_url = ""
        self._glb_url = ""
        self._pano_url = ""
        self._semantics = {}


def _import_on_main(ply_path, glb_path, pano_url, label, semantics, on_done, on_error):
    """Run the import on the main thread, then clean up temp files."""
    try:
        from mixar.modules.moodboard.core.world_labs_importer import (
            import_world_labs_world,
        )
        names = import_world_labs_world(
            ply_path, glb_path, name=label or "World", semantics=semantics,
        )
        if not names:
            on_error("World imported but produced no objects")
            return
        # The pano is a 360 interior of the room Marble rendered from the input
        # viewpoint. Drop it on the moodboard as a room-appearance reference the
        # agent can inspect ("world_interior"). Never fail the import over it.
        if pano_url:
            _import_pano_to_moodboard(pano_url)
        try:
            bpy.ops.ed.undo_push(message="World Labs: Import World")
        except Exception:  # noqa: BLE001
            pass
        on_done(", ".join(names))
    except Exception as e:  # noqa: BLE001
        logger.error("[WorldLabs] import failed: %s", e)
        on_error(f"Failed to import world: {e}")
    finally:
        import shutil

        for path in (ply_path, glb_path):
            if not path or not os.path.exists(path):
                continue
            try:
                parent = os.path.dirname(path)
                if os.path.basename(parent).startswith("worldlabs_"):
                    shutil.rmtree(parent, ignore_errors=True)
                else:
                    os.unlink(path)
            except OSError:
                pass


def _import_pano_to_moodboard(pano_url: str) -> None:
    """Load the World Labs pano and add it to the moodboard as ``world_interior``.

    Best-effort: the pano is a nice-to-have appearance reference, so any failure
    is logged and swallowed rather than surfaced to the user.
    """
    try:
        from mixar.modules.common.utils.image_utils import (
            add_image_to_moodboard,
            load_image_from_url,
        )
        image = load_image_from_url(pano_url, name="world_interior")
        if image is None:
            return
        add_image_to_moodboard(image, prompt="World interior (360 pano)")
    except Exception as e:  # noqa: BLE001
        logger.warning("[WorldLabs] pano -> moodboard failed: %s", e)


def _download_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as resp:
        return resp.read()


def _download_and_convert_spz(url: str, label: str = "") -> str:
    """Download the SPZ, convert to 3DGS PLY, write to a temp file, return path.

    The temp PLY keeps a human stem (the job label): the KIRI importer names
    the created object after the PLY file, so an mkstemp name leaks gibberish
    object names like ``worldlabs_wy9cyeh9`` into the scene.
    """
    import re

    from mixar.modules.moodboard.core.world_labs_spz import spz_to_ply

    spz_bytes = _download_bytes(url)
    ply_bytes = spz_to_ply(spz_bytes)
    stem = re.sub(r"[^\w\- ]+", "", label).strip() or "world"
    temp_dir = tempfile.mkdtemp(prefix="worldlabs_")
    path = os.path.join(temp_dir, f"{stem}.ply")
    with open(path, "wb") as f:
        f.write(ply_bytes)
    return path


def _download_glb(url: str) -> str:
    glb_bytes = _download_bytes(url)
    fd, path = tempfile.mkstemp(suffix=".glb", prefix="worldlabs_")
    with os.fdopen(fd, "wb") as f:
        f.write(glb_bytes)
    return path


# ---------------------------------------------------------------------------
# Enqueue helper + queue listener
# ---------------------------------------------------------------------------

_listener_attached = False


def enqueue_world_labs_job(
    *,
    mode: str,
    prompt: str,
    model: str,
    lod: str = "500k",
    image_bytes_b64: str = "",
    label: str = "",
) -> Optional[WorldLabsJob]:
    """Build a ``WorldLabsJob`` and submit it to the queue."""
    job = WorldLabsJob(
        feature_key=FEATURE_WORLD_LABS,
        service=_SERVICE_KEY,
        label=label or (prompt[:40] if prompt else "World"),
        mode=mode,
        prompt=prompt,
        model=model,
        lod=lod,
        image_bytes_b64=image_bytes_b64,
    )
    queue = _get_world_labs_queue()
    if not queue.submit(job):
        logger.warning("[WorldLabs] duplicate job rejected: %s", job.label)
        return None
    return job


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Redraw the MIXIE sidebar so progress / completion state stays in sync."""
    try:
        for area in bpy.context.screen.areas:
            if area.type == "MIXIE":
                area.tag_redraw()
    except Exception:  # noqa: BLE001
        pass


def _get_world_labs_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_WORLD_LABS)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
