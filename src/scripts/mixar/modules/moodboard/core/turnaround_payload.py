# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Multi-View Submit Payload

Turns the Model Gen tab's Input Image plus its turnaround group into the
multi-view fragment of a 3D-generation job payload. Split out of
:mod:`turnaround_views` (which owns the group data model) to stay under the
500-line file limit; the dependency runs one way, payload -> data model.

Shape, frozen against ``POST /job-queue/jobs``::

    {"image_s3_key": "<input image key>",
     "multi_view_images": [{"s3_key": "...", "view_type": "left"}, ...]}

The Input Image is the vendor's single frontal image and is NEVER a group
member, so it can never leak into ``multi_view_images``.
"""

from typing import List, Tuple

from mixar.config.logging_config import get_logger

from .turnaround_views import (
    allowed_view_types, group_items, moodboard_item_for,
)

logger = get_logger(__name__)


def _encode_image(image) -> str:
    """Base64 JPEG bytes for a view the backend has no S3 key for.

    Only manually added views take this path — detected crops already live in
    S3. Uses the single-image 3D profile because a manually added view IS one
    of the per-view inputs (it is never split further).
    """
    import base64

    from mixar.modules.common.utils.image_utils import compress_for_service

    data = compress_for_service(image, "image_to_3d")
    if not data:
        raise ValueError(f"'{image.name}' has no pixel data")
    return base64.b64encode(data).decode()


def _view_entry(item) -> dict:
    """One ``multi_view_images`` entry for a companion view.

    Detected crops forward their S3 key verbatim; manually added views carry
    their pixels inline. The backend accepts a mixed list — job_queue's upload
    stage only touches entries that carry ``image_bytes_b64``.
    """
    if item.s3_key:
        return {"s3_key": item.s3_key, "view_type": item.view_type}
    return {
        "image_bytes_b64": _encode_image(item.image),
        "filename": f"{item.view_type}.png",
        "view_type": item.view_type,
    }


def build_multi_view_payload(
    scene,
    group_id: str,
    main_image,
    model_slug: str = "",
) -> Tuple[dict, List[str]]:
    """Build the multi-view fragment of a 3D-generation job payload.

    *main_image* is the Model Gen tab's Input Image — the vendor's single
    frontal image. It is NOT a group member; the group supplies the companion
    angles only. Returns ``(payload_fragment, warnings)``::

        {"image_s3_key": "<main key>",
         "multi_view_images": [{"s3_key": "...", "view_type": "left"}, ...]}

    Detected crops already live in S3 (the detect-views endpoint put them
    there under ``user-uploads/<user_id>/turnaround/...``), so their keys are
    forwarded VERBATIM rather than the pixels being re-uploaded. Job submit
    validates that each key belongs to the calling user — never rewrite or
    synthesise a key client-side. Views the user added by hand have no key,
    so those carry inline base64 pixels instead; the two shapes mix freely
    within one payload.

    Angles the selected model cannot take (3.1-only angles on a 3.0 model) are
    dropped with a warning here rather than submitted for the vendor to reject
    after credits have been held.

    Raises ``ValueError`` when the fragment cannot be built — callers should
    surface the message and fall back to nothing, never to a malformed job.
    """
    if main_image is None:
        raise ValueError("Add an input image before generating")

    items = group_items(scene, group_id)
    if not items:
        raise ValueError("Multi-view set has no images")

    warnings: List[str] = []
    payload = _main_fragment(scene, main_image)

    allowed = allowed_view_types(model_slug)
    seen = set()
    multi_views = []
    for item in items:
        if item.image == main_image:
            # Belt and braces: the input image should never be a member.
            continue
        if item.view_type not in allowed:
            warnings.append(
                f"'{item.image.name}' is a {item.view_type} view, which "
                f"'{model_slug}' does not accept — it was not sent"
            )
            continue
        if item.view_type in seen:
            warnings.append(
                f"More than one '{item.view_type}' view — kept only the first"
            )
            continue
        seen.add(item.view_type)
        multi_views.append(_view_entry(item))

    if multi_views:
        payload["multi_view_images"] = multi_views
    return payload, warnings


def _main_fragment(scene, main_image) -> dict:
    """Primary-image half of the payload — S3 key when we have one."""
    item = moodboard_item_for(scene, main_image)
    s3_key = getattr(item, 's3_key', "") if item is not None else ""
    if s3_key:
        return {"image_s3_key": s3_key}
    return {
        "image_bytes_b64": _encode_image(main_image),
        "image_filename": "image.png",
    }
