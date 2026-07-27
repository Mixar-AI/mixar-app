# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Turnaround / Model-Sheet View Detection

A turnaround (model sheet) is a single image showing the same character from
several angles. Sending the whole sheet to an image-to-3D engine makes it try
to model every panel as one object, which produces garbage.

This module calls ``POST /api/v1/model-3d/detect-views``, brings the returned
per-view crops into the moodboard as ordinary moodboard images tagged with a
shared ``turnaround_group``, and builds the S3-key multi-view payload used at
submit time so the crops never have to be uploaded a second time.

Threading: the detect request runs on the shared async request queue, whose
callbacks are delivered on Blender's main thread. Crop pixels are downloaded
on a worker thread and handed back to the main thread before touching
``bpy.data``.
"""

import threading
import uuid
from typing import Callable, List, Tuple

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    MOODBOARD_IMAGE_BASE_SIZE,
    MOODBOARD_MULTI_IMAGE_GAP,
    TURNAROUND_FALLBACK_MULTI_VIEW_SLUGS,
    TURNAROUND_VIEW_FRONT,
    TURNAROUND_VIEW_NONE,
    TURNAROUND_VIEW_TYPES,
)

logger = get_logger(__name__)

# Valid ids the backend may return / the user may pick, minus the sentinel.
VALID_VIEW_TYPES = tuple(
    item[0] for item in TURNAROUND_VIEW_TYPES if item[0] != TURNAROUND_VIEW_NONE
)

# Backend hard ceiling for the detect-views upload (core/validators.py also
# enforces 4096x4096, which the "turnaround_detect" compression profile
# handles). Checked client-side so an oversized sheet gets a clear message
# rather than a generic 422.
DETECT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Group queries
# ---------------------------------------------------------------------------

def find_group_for_image(scene, image) -> str:
    """Return the turnaround group id of *image*, or "" when it has none."""
    if image is None or not hasattr(scene, 'mixie_moodboard_images'):
        return ""
    for item in scene.mixie_moodboard_images:
        if item.image == image and item.turnaround_group:
            return item.turnaround_group
    return ""


def group_items(scene, group_id: str) -> list:
    """Moodboard items belonging to *group_id*, front first then as stored."""
    if not group_id or not hasattr(scene, 'mixie_moodboard_images'):
        return []
    items = [
        item for item in scene.mixie_moodboard_images
        if item.turnaround_group == group_id and item.image
    ]
    items.sort(key=lambda it: 0 if it.view_type == TURNAROUND_VIEW_FRONT else 1)
    return items


def clear_group(scene, group_id: str) -> int:
    """Detach every item from *group_id* so it submits as a single image.

    Returns the number of items cleared. The images themselves are left on the
    moodboard — only the grouping/labelling is dropped.
    """
    if not group_id or not hasattr(scene, 'mixie_moodboard_images'):
        return 0
    cleared = 0
    for item in scene.mixie_moodboard_images:
        if item.turnaround_group == group_id:
            item.turnaround_group = ""
            item.view_type = TURNAROUND_VIEW_NONE
            item.s3_key = ""
            cleared += 1
    return cleared


# ---------------------------------------------------------------------------
# Multi-view gating
# ---------------------------------------------------------------------------

def model_accepts_multi_view(service_key: str, model_slug: str) -> bool:
    """True when *model_slug* can take multi-view input.

    Prefers the catalog's per-model ``supports_multi_view`` flag. Falls back
    to a known-slug list only when the catalog has not populated the flag
    (offline / pre-auth), so Detect Views stays usable before login.
    """
    try:
        from mixar.modules.common.generation_params import (
            model_supports_multi_view,
        )
        if model_supports_multi_view(service_key, model_slug):
            return True
    except Exception:
        pass
    return (model_slug or "").strip().lower() in TURNAROUND_FALLBACK_MULTI_VIEW_SLUGS


# ---------------------------------------------------------------------------
# Submit payload
# ---------------------------------------------------------------------------

def _count_word(count: int) -> str:
    """Small counts read better as words in a user-facing error."""
    return {2: "Two", 3: "Three", 4: "Four"}.get(count, str(count))


def build_multi_view_payload(scene, group_id: str) -> Tuple[dict, List[str]]:
    """Build the S3-key multi-view fragment of a ``model_3d`` job payload.

    Returns ``(payload_fragment, warnings)`` where the fragment looks like::

        {"image_s3_key": "<front key>",
         "multi_view_images": [{"s3_key": "...", "view_type": "left"}, ...]}

    The crops already live in S3 (the detect-views endpoint put them there
    under ``user-uploads/<user_id>/turnaround/...``), so keys are forwarded
    VERBATIM rather than the pixels being re-uploaded. Job submit validates
    that each key belongs to the calling user — never rewrite or synthesise
    a key client-side.

    Raises ``ValueError`` when the group cannot produce a valid payload —
    callers should surface the message and fall back to nothing, never to a
    malformed job.
    """
    items = group_items(scene, group_id)
    if not items:
        raise ValueError("Turnaround group has no images")

    missing_keys = [it for it in items if not it.s3_key]
    if missing_keys:
        raise ValueError(
            "Some views are missing their backend key — run Detect Views again"
        )

    fronts = [it for it in items if it.view_type == TURNAROUND_VIEW_FRONT]
    if not fronts:
        raise ValueError("Label one of the views 'Front' before generating")
    if len(fronts) > 1:
        # Refuse rather than silently picking one. The next step is a
        # multi-minute, ~50-credit job; quietly dropping a panel would build
        # the model from less data than the user believes they supplied, and
        # a warning is easy to miss mid-flow. Failing costs a two-second fix.
        raise ValueError(
            f"{_count_word(len(fronts))} views are labelled Front — "
            "only one can be the main image"
        )

    warnings: List[str] = []
    primary = fronts[0]
    payload = {"image_s3_key": primary.s3_key}

    # The vendor's multi-view enum has no "front" member, so every remaining
    # front-labelled panel is dropped rather than sent and rejected. Duplicate
    # view types are also dropped — the vendor accepts each angle once.
    seen = set()
    multi_views = []
    for item in items:
        # Only *primary* reaches this — a multi-front group already raised.
        if item.view_type == TURNAROUND_VIEW_FRONT:
            continue
        if item.view_type == TURNAROUND_VIEW_NONE:
            warnings.append(f"'{item.image.name}' has no view label — skipped")
            continue
        if item.view_type in seen:
            warnings.append(
                f"More than one '{item.view_type}' view — kept only the first"
            )
            continue
        seen.add(item.view_type)
        multi_views.append({"s3_key": item.s3_key, "view_type": item.view_type})

    if multi_views:
        payload["multi_view_images"] = multi_views
    return payload, warnings


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

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

    Guarantees at most one ``front`` panel and puts it first, matching the
    endpoint contract without trusting the response to already satisfy it.
    """
    panels = []
    seen_front = False
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
        if view_type == TURNAROUND_VIEW_FRONT:
            if seen_front:
                logger.warning("[Turnaround] Extra front panel — skipped")
                continue
            seen_front = True
        panels.append(
            {"view_type": view_type, "s3_key": s3_key, "preview_url": preview_url}
        )

    panels.sort(key=lambda p: 0 if p["view_type"] == TURNAROUND_VIEW_FRONT else 1)
    if not panels or panels[0]["view_type"] != TURNAROUND_VIEW_FRONT:
        logger.warning("[Turnaround] Response has no front panel")
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
    group_id = f"turnaround_{uuid.uuid4().hex[:12]}"
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
