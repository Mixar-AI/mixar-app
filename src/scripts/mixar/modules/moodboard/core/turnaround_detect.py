# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Turnaround / Model-Sheet View Detection

Calls ``POST /api/v1/model-3d/detect-views`` with a turnaround sheet and
brings the returned per-view crops onto the moodboard. The group model itself
(queries, labelling, submit payload) lives in :mod:`turnaround_views`.

Backend contract, and how each panel is ingested:

- ``panels[0].view_type`` is always ``"main"`` — the sheet's front
  orthographic, falling back to its hero render when there is no front. It
  becomes the tab's **Input Image** and is NOT a group member.
- ``"hero"`` appears only when the sheet has BOTH. No vendor ``ViewType``
  describes it, so it is not a companion either: it lands on the moodboard
  untagged next to the main, as an alternative Input Image the user can
  promote when a stylised sheet reconstructs badly.
- everything else is one of the seven vendor angles and joins the group.

Both main and hero keep their ``s3_key``, so whichever one ends up as the
Input Image submits by key instead of re-uploading pixels.

Threading: the detect request runs on the shared async request queue, whose
callbacks are delivered on Blender's main thread. Crop pixels are downloaded
on a worker thread and handed back to the main thread before touching
``bpy.data``.
"""

import threading
from typing import Callable, Optional, Tuple

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    DETECT_PANEL_HERO,
    DETECT_PANEL_MAIN,
    MOODBOARD_IMAGE_BASE_SIZE,
    MOODBOARD_MULTI_IMAGE_GAP,
    TURNAROUND_MAX_COMPANIONS,
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
    hint: str = "",
) -> None:
    """Detect turnaround panels in *image* and ingest the crops.

    All three callbacks fire on Blender's main thread.

    Args:
        image: The moodboard image believed to be a turnaround sheet.
        on_done: ``fn(group_id, companion_count)`` after crops are on the
            board. ``group_id`` is "" when the sheet had no companion angles.
        on_error: ``fn(message)`` on any failure.
        on_not_turnaround: called when the backend says this is an ordinary
            single image — the caller should change nothing.
        hint: optional one-line description of the subject, forwarded as the
            endpoint's ``hint`` form field to help it read stylised sheets.
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
        hint=(hint or "").strip(),
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

    Returns them in ingest order — ``main``, then ``hero`` if present, then
    the companion angles — enforcing the endpoint contract
    (``panels[0].view_type == "main"``, at most one main, at most one hero)
    rather than trusting the response to already satisfy it. Without a main
    panel there is no input image, so an unusable response is dropped entirely
    and the caller falls back to the ordinary single-image path.

    Companions are capped at the vendor's seven; extras beyond that would be
    rejected server-side after credits are held.
    """
    order = {DETECT_PANEL_MAIN: 0, DETECT_PANEL_HERO: 1}
    panels = []
    seen = set()
    companions = 0
    for panel in raw_panels:
        if not isinstance(panel, dict):
            continue
        preview_url = panel.get("preview_url")
        s3_key = panel.get("s3_key")
        view_type = panel.get("view_type")
        if not preview_url or not s3_key:
            continue
        if view_type in order:
            if view_type in seen:
                logger.warning("[Turnaround] Extra %s panel — skipped", view_type)
                continue
            seen.add(view_type)
        elif view_type not in VALID_VIEW_TYPES:
            logger.warning("[Turnaround] Unknown view_type %r — skipped", view_type)
            continue
        else:
            if companions >= TURNAROUND_MAX_COMPANIONS:
                logger.warning(
                    "[Turnaround] More than %s companion views — %r skipped",
                    TURNAROUND_MAX_COMPANIONS, view_type,
                )
                continue
            companions += 1
        panels.append(
            {"view_type": view_type, "s3_key": s3_key, "preview_url": preview_url}
        )

    panels.sort(key=lambda p: order.get(p["view_type"], 2))
    if not panels or panels[0]["view_type"] != DETECT_PANEL_MAIN:
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
    """Main-thread: load each crop onto the board and wire up the tab.

    ``main`` becomes the tab's Input Image and ``hero`` sits beside it,
    neither joining the group — only the companion angles do, matching what
    the vendor payload actually has slots for. ``main`` is instead marked with
    ``turnaround_main_group``, which is what BINDS this set to that one image:
    the companions ride along only when this crop is the image being
    converted, never when some unrelated board image is.
    Returns ``(group_id, companions)``; ``group_id`` is "" when the sheet
    yielded no companion angles at all (a perfectly good single-image result,
    just not a multi-view one).
    """
    import os

    from .turnaround_views import set_active_group, set_tab_input_image

    scene = bpy.context.scene
    group_id = new_group_id()
    origin_x, origin_y, step = _strip_origin(scene, source_name)

    loaded = 0
    companions = 0
    main_image = None
    main_item = None
    for index, (temp_path, panel) in enumerate(downloaded):
        view_type = panel["view_type"]
        img = _load_crop(temp_path, f"{base}_{view_type}")
        if img is None:
            continue

        item = _place(scene, img, origin_x + index * step, origin_y)
        item.s3_key = panel["s3_key"]
        loaded += 1

        if view_type == DETECT_PANEL_MAIN:
            main_image = img
            main_item = item
        elif view_type == DETECT_PANEL_HERO:
            # Untagged: no vendor ViewType describes a hero render, so it can
            # only ever be used by promoting it to Input Image.
            pass
        else:
            item.view_type = view_type
            item.turnaround_group = group_id
            companions += 1

    if not loaded:
        raise RuntimeError("No crops could be loaded")

    # The user's next Generate then naturally takes the multi-view path
    # without them having to hunt for the right crop on the canvas. Only when
    # companions actually exist: a no-companion sheet is a single-image
    # result, and marking its main would bind an empty set.
    if main_item is not None and companions:
        main_item.turnaround_main_group = group_id
    set_tab_input_image(scene, main_image)
    set_active_group(scene, group_id if companions else "")
    return (group_id if companions else ""), companions


def _load_crop(temp_path: str, name: str) -> Optional["bpy.types.Image"]:
    """Load one downloaded crop, always removing the temp file."""
    import os

    from mixar.modules.common.utils.image_utils import load_image_from_file

    try:
        return load_image_from_file(temp_path, name)
    except Exception as e:
        logger.error("[Turnaround] Failed to load crop: %s", e)
        return None
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _place(scene, image, x: float, y: float):
    """Append *image* to the moodboard and return its item."""
    from mixar.modules.common.utils.image_utils import add_image_to_moodboard

    add_image_to_moodboard(image, position_x=x, position_y=y)
    # add_image_to_moodboard appends, so the new item is the last one.
    return scene.mixie_moodboard_images[-1]


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
