# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Turnaround / Model-Sheet View Detection

Calls ``POST /api/v1/model-3d/detect-views`` with a turnaround sheet and
brings the returned per-view crops onto the moodboard as ordinary moodboard
images sharing a ``turnaround_group``. The group model itself (queries,
labelling, submit payload) lives in :mod:`turnaround_views`.

Backend contract: ``panels[0].view_type`` is always ``"main"`` — the sheet's
hero pose when it has one, its front orthographic otherwise. ``"front"`` only
appears alongside a hero and is NOT submittable (see constants.py).

Threading: the detect request runs on the shared async request queue, whose
callbacks are delivered on Blender's main thread. Crop pixels are downloaded
on a worker thread and handed back to the main thread before touching
``bpy.data``.
"""

import threading
from typing import Callable, Tuple

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    MOODBOARD_IMAGE_BASE_SIZE,
    MOODBOARD_MULTI_IMAGE_GAP,
    TURNAROUND_VIEW_MAIN,
)
from .turnaround_views import VALID_VIEW_TYPES, new_group_id

logger = get_logger(__name__)

# Backend hard ceiling for the detect-views upload (core/validators.py also
# enforces 4096x4096, which the "turnaround_detect" compression profile
# handles). Checked client-side so an oversized sheet gets a clear message
# rather than a generic 422.
DETECT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024



def detect_views(
    image: bpy.types.Image,
    on_done: Callable[[str, int], None],
    on_error: Callable[[str], None],
    on_not_turnaround: Callable[[], None],
) -> None:
    """Detect turnaround panels in *image* and ingest the crops.

    All three callbacks fire on Blender's main thread.

    Args:
        image: The moodboard image believed to be a turnaround sheet.
        on_done: ``fn(group_id, panel_count)`` after crops are on the board.
        on_error: ``fn(message)`` on any failure.
        on_not_turnaround: called when the backend says this is an ordinary
            single image — the caller should change nothing.
    """
    from mixar.modules.common.api.services import get_model_3d_service
    from mixar.modules.common.utils.image_utils import compress_for_service

    # Dedicated profile, NOT the image_to_3d one: the sheet gets split, so
    # its upload resolution divides down into the per-view 3D input.
    try:
        image_bytes = compress_for_service(image, "turnaround_detect")
    except Exception as e:
        on_error(f"Failed to read image: {e}")
        return
    if not image_bytes:
        on_error("Image has no pixel data")
        return
    if len(image_bytes) > DETECT_MAX_UPLOAD_BYTES:
        # The backend rejects oversized uploads with a generic 422; say what
        # actually went wrong instead.
        on_error(
            f"Image is too large to analyse "
            f"({len(image_bytes) / (1024 * 1024):.1f} MB, limit 20 MB)"
        )
        return

    source_name = image.name

    def _on_success(response):
        # The client wraps the whole envelope in response.data; unwrap the
        # inner payload the same way the other moodboard services do.
        envelope = response.data or {}
        data = envelope.get("data", envelope)

        if not data.get("is_turnaround"):
            on_not_turnaround()
            return

        panels = _sanitise_panels(data.get("panels") or [])
        if not panels:
            on_not_turnaround()
            return

        _ingest_panels(source_name, panels, on_done, on_error)

    def _on_error(error):
        logger.error("[Turnaround] detect-views failed: %s", error)
        on_error(_error_message(error))

    get_model_3d_service().detect_views_async(
        image_bytes,
        filename="turnaround.jpg",
        on_success=_on_success,
        on_error=_on_error,
    )


def _error_message(error) -> str:
    """User-facing message for a failed detect-views call.

    Reuses the job queue's shared error classifier (402 -> out of credits,
    etc.) but calls out 502 specially: detection itself failed vendor-side,
    the credits were refunded, and retrying is worthwhile. That is distinct
    from a 200 with ``is_turnaround: false``, which is not an error at all.
    """
    from mixar.modules.common.job_queue.core.error_helpers import (
        classify_error, sanitize_message,
    )

    if getattr(error, "status_code", None) == 502:
        return "View detection failed — no credits were used, please try again"
    return classify_error(error) or sanitize_message(
        str(error), "View detection failed"
    )


def _sanitise_panels(raw_panels: list) -> list:
    """Keep only panels with a usable preview URL, key and known view type.

    Guarantees at most one ``main`` panel and puts it first, matching the
    endpoint contract (``panels[0].view_type == "main"``) without trusting the
    response to already satisfy it. A group with no main image cannot be
    submitted at all, so an unusable response is dropped entirely and the
    caller falls back to the ordinary single-image path.
    """
    panels = []
    seen_main = False
    for panel in raw_panels:
        if not isinstance(panel, dict):
            continue
        preview_url = panel.get("preview_url")
        s3_key = panel.get("s3_key")
        view_type = panel.get("view_type")
        if not preview_url or not s3_key:
            continue
        if view_type not in VALID_VIEW_TYPES:
            logger.warning("[Turnaround] Unknown view_type %r — skipped", view_type)
            continue
        if view_type == TURNAROUND_VIEW_MAIN:
            if seen_main:
                logger.warning("[Turnaround] Extra main panel — skipped")
                continue
            seen_main = True
        panels.append(
            {"view_type": view_type, "s3_key": s3_key, "preview_url": preview_url}
        )

    panels.sort(key=lambda p: 0 if p["view_type"] == TURNAROUND_VIEW_MAIN else 1)
    if not panels or panels[0]["view_type"] != TURNAROUND_VIEW_MAIN:
        logger.warning("[Turnaround] Response has no main panel")
        return []
    return panels


def _ingest_panels(
    source_name: str,
    panels: list,
    on_done: Callable[[str, int], None],
    on_error: Callable[[str], None],
) -> None:
    """Download crops off-thread, then add them to the moodboard on the main
    thread. Preview URLs are short-lived, so they are fetched immediately."""
    base = _base_name(source_name)

    def _download():
        from mixar.modules.common.utils.image_utils import (
            download_image_to_tempfile,
        )
        downloaded = []
        for panel in panels:
            try:
                temp_path, _ = download_image_to_tempfile(panel["preview_url"])
            except Exception as e:
                logger.error(
                    "[Turnaround] Failed to download %s crop: %s",
                    panel["view_type"], e,
                )
                continue
            downloaded.append((temp_path, panel))

        def _apply():
            if not downloaded:
                on_error("Failed to download the detected views")
                return None
            try:
                group_id, count = _add_panels_to_moodboard(
                    source_name, base, downloaded)
            except Exception as e:
                logger.error("[Turnaround] Failed to add crops: %s", e, exc_info=True)
                on_error(f"Failed to add detected views: {e}")
                return None
            on_done(group_id, count)
            return None

        bpy.app.timers.register(_apply, first_interval=0.0)

    threading.Thread(target=_download, daemon=True).start()


def _add_panels_to_moodboard(source_name, base, downloaded) -> Tuple[str, int]:
    """Main-thread: load each crop and append it as a tagged moodboard item."""
    import os

    from mixar.modules.common.utils.image_utils import (
        add_image_to_moodboard, load_image_from_file,
    )

    scene = bpy.context.scene
    group_id = new_group_id()
    origin_x, origin_y, step = _strip_origin(scene, source_name)

    added = 0
    for index, (temp_path, panel) in enumerate(downloaded):
        try:
            img = load_image_from_file(temp_path, f"{base}_{panel['view_type']}")
        except Exception as e:
            logger.error("[Turnaround] Failed to load crop: %s", e)
            continue
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        add_image_to_moodboard(
            img,
            position_x=origin_x + index * step,
            position_y=origin_y,
        )
        # add_image_to_moodboard appends, so the new item is the last one.
        item = scene.mixie_moodboard_images[-1]
        item.view_type = panel["view_type"]
        item.s3_key = panel["s3_key"]
        item.turnaround_group = group_id
        added += 1

    if not added:
        raise RuntimeError("No crops could be loaded")
    return group_id, added


def _base_name(source_name: str) -> str:
    """Strip Blender's ``.001`` suffix and any extension from a source name."""
    name = source_name.rsplit('.', 1)
    if len(name) == 2 and (name[1].isdigit() or len(name[1]) <= 4):
        return name[0] or source_name
    return source_name


def _strip_origin(scene, source_name: str) -> Tuple[float, float, float]:
    """Canvas origin and horizontal step for the row of crops.

    Laid out left-to-right directly beneath the source sheet so the group
    reads as a strip; falls back to the canvas origin if the sheet is gone.
    """
    step = MOODBOARD_IMAGE_BASE_SIZE + MOODBOARD_MULTI_IMAGE_GAP
    for item in scene.mixie_moodboard_images:
        if item.image and item.image.name == source_name:
            offset = MOODBOARD_IMAGE_BASE_SIZE * max(item.scale, 0.1)
            return (
                item.position_x,
                item.position_y - offset - MOODBOARD_MULTI_IMAGE_GAP,
                step,
            )
    return 0.0, 0.0, step
