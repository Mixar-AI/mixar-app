# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Turnaround / Multi-View Group Model

A turnaround (model sheet) is a single image showing the same character from
several angles. Sending the whole sheet to an image-to-3D engine makes it try
to model every panel as one object, which produces garbage — so it is split
into per-view crops that submit as ONE multi-view job.

This module owns the *group* — the set of moodboard images sharing a
``turnaround_group``, each carrying a ``view_type`` label — plus the submit
payload built from it. A group can come from the backend detector
(:mod:`turnaround_detect`) or be assembled by hand in the sidebar; the two
mix freely, which is why a view may carry either an S3 key (detected, already
staged backend-side) or inline pixels (added by the user).

Exactly one item must be labelled ``main``; it becomes the job's primary
image. See ``constants.TURNAROUND_VIEW_TYPES`` for the label vocabulary.
"""

import uuid
from typing import List, Tuple

from mixar.config.logging_config import get_logger

from ..constants import (
    MOODBOARD_IMAGE_BASE_SIZE,
    MOODBOARD_MULTI_IMAGE_GAP,
    TURNAROUND_FALLBACK_MULTI_VIEW_SLUGS,
    TURNAROUND_VIEW_FRONT,
    TURNAROUND_VIEW_MAIN,
    TURNAROUND_VIEW_NONE,
    TURNAROUND_VIEW_TYPES,
)

logger = get_logger(__name__)

# Valid ids the backend may return / the user may pick, minus the sentinel.
VALID_VIEW_TYPES = tuple(
    item[0] for item in TURNAROUND_VIEW_TYPES if item[0] != TURNAROUND_VIEW_NONE
)


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
    """Moodboard items belonging to *group_id*, main first then as stored."""
    if not group_id or not hasattr(scene, 'mixie_moodboard_images'):
        return []
    items = [
        item for item in scene.mixie_moodboard_images
        if item.turnaround_group == group_id and item.image
    ]
    items.sort(key=lambda it: 0 if it.view_type == TURNAROUND_VIEW_MAIN else 1)
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
            _detach(item)
            cleared += 1
    return cleared


def detach_image(scene, group_id: str, image) -> bool:
    """Drop a single *image* out of *group_id*, keeping the rest intact.

    The per-row counterpart of :func:`clear_group`: the image stays on the
    moodboard, it just stops being one of the job's views. Returns True when
    an item was actually detached.
    """
    if not group_id or image is None:
        return False
    if not hasattr(scene, 'mixie_moodboard_images'):
        return False
    for item in scene.mixie_moodboard_images:
        if item.turnaround_group == group_id and item.image == image:
            _detach(item)
            return True
    return False


def _detach(item) -> None:
    """Strip every turnaround marker from a moodboard item."""
    item.turnaround_group = ""
    item.view_type = TURNAROUND_VIEW_NONE
    # The S3 key is scoped to the detected group; a re-detect mints a new one.
    item.s3_key = ""


def new_group_id() -> str:
    """Mint an id for a group the user is assembling by hand."""
    return f"turnaround_{uuid.uuid4().hex[:12]}"


def attach_image(scene, group_id: str, image, view_type=TURNAROUND_VIEW_NONE):
    """Make *image* a member of *group_id*, returning its moodboard item.

    An image already on the board is tagged in place — never duplicated — so
    the user can promote the tab's current input image into a hand-built
    group. Anything else is appended to the end of the group's strip, matching
    how detected crops are laid out.
    """
    if image is None or not group_id:
        return None
    if not hasattr(scene, 'mixie_moodboard_images'):
        return None

    for item in scene.mixie_moodboard_images:
        if item.image == image:
            item.turnaround_group = group_id
            item.view_type = view_type
            return item

    from mixar.modules.common.utils.image_utils import add_image_to_moodboard

    x, y = _next_strip_slot(scene, group_id)
    add_image_to_moodboard(image, position_x=x, position_y=y)
    # add_image_to_moodboard appends, so the new item is the last one.
    item = scene.mixie_moodboard_images[-1]
    item.turnaround_group = group_id
    item.view_type = view_type
    return item


def set_main_image(scene, group_id: str, image):
    """Make *image* the group's single ``main`` view.

    Any previous main is demoted to unlabelled rather than guessed at — only
    the user knows what angle it actually was, and an unlabelled view is
    surfaced by the panel's own validation hint.
    """
    target = None
    for item in group_items(scene, group_id):
        if item.image == image:
            target = item
        elif item.view_type == TURNAROUND_VIEW_MAIN:
            item.view_type = TURNAROUND_VIEW_NONE
    if target is not None:
        target.view_type = TURNAROUND_VIEW_MAIN
    return target


def main_item(scene, group_id: str):
    """The group's single main-labelled item, or None when 0 or 2+ are."""
    mains = [
        it for it in group_items(scene, group_id)
        if it.view_type == TURNAROUND_VIEW_MAIN
    ]
    return mains[0] if len(mains) == 1 else None


def _next_strip_slot(scene, group_id: str):
    """Canvas position just right of the group's rightmost member.

    ``(None, None)`` when the group is empty — ``add_image_to_moodboard``
    then places the image near the centre of the visible viewport.
    """
    items = group_items(scene, group_id)
    if not items:
        return None, None
    rightmost = max(items, key=lambda it: it.position_x)
    step = MOODBOARD_IMAGE_BASE_SIZE + MOODBOARD_MULTI_IMAGE_GAP
    return rightmost.position_x + step, rightmost.position_y


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


def build_multi_view_payload(scene, group_id: str) -> Tuple[dict, List[str]]:
    """Build the multi-view fragment of a ``model_3d`` job payload.

    Returns ``(payload_fragment, warnings)`` where the fragment looks like::

        {"image_s3_key": "<main key>",
         "multi_view_images": [{"s3_key": "...", "view_type": "left"}, ...]}

    Detected crops already live in S3 (the detect-views endpoint put them
    there under ``user-uploads/<user_id>/turnaround/...``), so their keys are
    forwarded VERBATIM rather than the pixels being re-uploaded. Job submit
    validates that each key belongs to the calling user — never rewrite or
    synthesise a key client-side. Views the user added by hand have no key,
    so those carry inline base64 pixels instead; the two shapes mix freely
    within one payload.

    Raises ``ValueError`` when the group cannot produce a valid payload —
    callers should surface the message and fall back to nothing, never to a
    malformed job.
    """
    items = group_items(scene, group_id)
    if not items:
        raise ValueError("Turnaround group has no images")

    mains = [it for it in items if it.view_type == TURNAROUND_VIEW_MAIN]
    if not mains:
        raise ValueError(
            "Label one of the views 'Main Image' before generating")
    if len(mains) > 1:
        # Refuse rather than silently picking one. The next step is a
        # multi-minute, ~50-credit job; quietly dropping a panel would build
        # the model from less data than the user believes they supplied, and
        # a warning is easy to miss mid-flow. Failing costs a two-second fix.
        raise ValueError(
            f"{_count_word(len(mains))} views are labelled Main Image — "
            "only one can be the main image"
        )

    warnings: List[str] = []
    primary = mains[0]
    if primary.s3_key:
        payload = {"image_s3_key": primary.s3_key}
    else:
        payload = {
            "image_bytes_b64": _encode_image(primary.image),
            "image_filename": "image.png",
        }

    # Duplicate view types are dropped — the vendor accepts each angle once.
    seen = set()
    multi_views = []
    for item in items:
        # Only *primary* reaches this — a multi-main group already raised.
        if item.view_type == TURNAROUND_VIEW_MAIN:
            continue
        if item.view_type == TURNAROUND_VIEW_FRONT:
            # The vendor's multi-view enum has no "front" member, so a front
            # orthographic that is not the main image cannot be sent at all.
            warnings.append(
                f"'{item.image.name}' is a front view — Hunyuan has no front "
                "slot, so it was not sent"
            )
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
        multi_views.append(_view_entry(item))

    if multi_views:
        payload["multi_view_images"] = multi_views
    return payload, warnings


