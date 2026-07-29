# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Turnaround / Multi-View Group Model

A turnaround (model sheet) is a single image showing the same character from
several angles. Sending the whole sheet to an image-to-3D engine makes it try
to model every panel as one object, which produces garbage — so it is split
into per-view crops that submit as ONE multi-view job.

The shape mirrors the vendor's: Hunyuan Pro takes **one frontal image plus up
to seven angles**. The frontal image is the Model Gen tab's **Input Image**;
the turnaround group holds the seven *companions* only, each carrying a
``view_type`` from ``constants.TURNAROUND_VIEW_TYPES`` (exactly the vendor's
``ViewType`` enum). There is deliberately no 'main', 'front' or 'none' label:
membership is ``turnaround_group != ""``, and the main image is whatever the
tab currently points at.

Groups come from the backend detector (:mod:`turnaround_detect`) or are
assembled from the moodboard selection, and the two mix freely — which is why
a companion may carry either an S3 key (detected, already staged backend-side)
or inline pixels (added by the user).

The active group id lives on the tab (``tab_image_to_3d.turnaround_group``),
not on the input image, so both input sources — selected moodboard image and
file-picked reference image — resolve it identically.
"""

import uuid
from typing import List, Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import (
    MOODBOARD_IMAGE_BASE_SIZE,
    MOODBOARD_MULTI_IMAGE_GAP,
    TURNAROUND_BASE_ANGLE_ONLY_SLUGS,
    TURNAROUND_MAX_COMPANIONS,
    TURNAROUND_VIEW_DEFAULT,
    TURNAROUND_VIEW_ORDER,
    TURNAROUND_VIEW_TYPES_V30,
)

logger = get_logger(__name__)

# Companion labels the backend may return / the user may pick.
VALID_VIEW_TYPES = TURNAROUND_VIEW_ORDER


# ---------------------------------------------------------------------------
# Active group — stored on the tab, not derived from an image
# ---------------------------------------------------------------------------

def _model_gen_tab(scene):
    """The Model Gen sidebar tab properties, or None."""
    sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
    return getattr(sidebar, 'tab_image_to_3d', None) if sidebar else None


def get_active_group(scene) -> str:
    """The tab's current multi-view group id, or "" when there is none.

    Self-healing on read: a group whose last companion was removed some other
    way (image deleted, undo) reports as absent rather than as an empty set.
    Deliberately does NOT write the property — this runs from draw code.
    """
    tab = _model_gen_tab(scene)
    group_id = (getattr(tab, 'turnaround_group', '') or "") if tab else ""
    if not group_id:
        return ""
    return group_id if group_items(scene, group_id) else ""


def set_active_group(scene, group_id: str) -> None:
    """Point the tab at *group_id* ("" to clear)."""
    tab = _model_gen_tab(scene)
    if tab is not None:
        tab.turnaround_group = group_id or ""


def get_tab_input_image(scene):
    """The Model Gen tab's current Input Image, or None.

    Mirrors ``ui.sidebar_ui_helpers.get_image_to_3d_input_image`` without the
    context dependency, so core code can resolve it too.
    """
    tab = _model_gen_tab(scene)
    if tab is None:
        return None
    if not getattr(tab, 'use_selected_image', False):
        return getattr(tab, 'reference_image', None)
    if not hasattr(scene, 'mixie_moodboard_images'):
        return None
    for item in scene.mixie_moodboard_images:
        if item.selected and item.image:
            return item.image
    return None


def set_tab_input_image(scene, image) -> None:
    """Make *image* the Model Gen tab's Input Image, whichever source it uses.

    BOTH paths are set: the moodboard selection (which the tab reads when
    "Use Selected Moodboard Image" is on) and ``reference_image`` (read when
    it is off), so promotion lands regardless of the toggle.
    """
    if image is None:
        return
    if hasattr(scene, 'mixie_moodboard_images'):
        for item in scene.mixie_moodboard_images:
            item.selected = (item.image == image)
    tab = _model_gen_tab(scene)
    if tab is not None and not getattr(tab, 'use_selected_image', False):
        tab.reference_image = image


def _forget_if_active(scene, group_id: str) -> None:
    """Clear the tab's group id once *group_id* has no members left."""
    tab = _model_gen_tab(scene)
    if tab is None:
        return
    if (getattr(tab, 'turnaround_group', '') or "") != group_id:
        return
    if not group_items(scene, group_id):
        tab.turnaround_group = ""


# ---------------------------------------------------------------------------
# Group queries
# ---------------------------------------------------------------------------

def find_group_for_image(scene, image) -> str:
    """Return the turnaround group id of *image*, or "" when it has none.

    Only companions are group members, so the tab's Input Image always
    answers "" — use :func:`get_active_group` for the active set.
    """
    if image is None or not hasattr(scene, 'mixie_moodboard_images'):
        return ""
    for item in scene.mixie_moodboard_images:
        if item.image == image and item.turnaround_group:
            return item.turnaround_group
    return ""


def group_items(scene, group_id: str) -> list:
    """Companion items of *group_id*, in canonical view-type order."""
    if not group_id or not hasattr(scene, 'mixie_moodboard_images'):
        return []
    items = [
        item for item in scene.mixie_moodboard_images
        if item.turnaround_group == group_id and item.image
    ]
    order = {view: index for index, view in enumerate(TURNAROUND_VIEW_ORDER)}
    items.sort(key=lambda it: order.get(it.view_type, len(order)))
    return items


def moodboard_item_for(scene, image):
    """The moodboard item wrapping *image*, or None when it is not on board.

    The Input Image may be a file-picked datablock that never reached the
    moodboard; callers fall back to inline pixels when this returns None.
    """
    if image is None or not hasattr(scene, 'mixie_moodboard_images'):
        return None
    for item in scene.mixie_moodboard_images:
        if item.image == image:
            return item
    return None


def used_view_types(scene, group_id: str) -> set:
    """View types already taken within *group_id*."""
    return {item.view_type for item in group_items(scene, group_id)}


def next_free_view_type(
    scene, group_id: str, allowed=None, taken=None
) -> str:
    """The next unassigned angle for *group_id*, or "" when the set is full.

    Handing out angles automatically is what makes "Add Selected" a one-click
    path: the common left/right/back turnaround never needs the dropdown.
    *taken* lets a caller reserve angles it is about to assign in the same
    batch, before any of them has been written back.
    """
    allowed = tuple(allowed) if allowed is not None else TURNAROUND_VIEW_ORDER
    occupied = set(used_view_types(scene, group_id))
    if taken:
        occupied |= set(taken)
    for view_type in TURNAROUND_VIEW_ORDER:
        if view_type in allowed and view_type not in occupied:
            return view_type
    return ""


def remaining_capacity(scene, group_id: str) -> int:
    """How many more companions *group_id* can hold (vendor cap is 7)."""
    return max(0, TURNAROUND_MAX_COMPANIONS - len(group_items(scene, group_id)))


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
    if cleared:
        _forget_if_active(scene, group_id)
    return cleared


def detach_image(scene, group_id: str, image, keep_s3_key: bool = False) -> bool:
    """Drop a single *image* out of *group_id*, keeping the rest intact.

    The per-row counterpart of :func:`clear_group`: the image stays on the
    moodboard, it just stops being one of the job's companion views. Pass
    *keep_s3_key* when the image is being promoted to Input Image — the key is
    still a valid upload of those exact pixels, and keeping it saves
    re-encoding them at submit time.
    """
    if not group_id or image is None:
        return False
    if not hasattr(scene, 'mixie_moodboard_images'):
        return False
    for item in scene.mixie_moodboard_images:
        if item.turnaround_group == group_id and item.image == image:
            _detach(item, keep_s3_key=keep_s3_key)
            _forget_if_active(scene, group_id)
            return True
    return False


def _detach(item, keep_s3_key: bool = False) -> None:
    """Strip the turnaround markers from a moodboard item."""
    item.turnaround_group = ""
    item.view_type = TURNAROUND_VIEW_DEFAULT
    if not keep_s3_key:
        # The S3 key is scoped to the detected group; a re-detect mints a new
        # one. Promotion is the exception — see detach_image().
        item.s3_key = ""


def new_group_id() -> str:
    """Mint an id for a group the user is assembling by hand."""
    return f"turnaround_{uuid.uuid4().hex[:12]}"


def attach_image(scene, group_id: str, image, view_type=TURNAROUND_VIEW_DEFAULT):
    """Make *image* a companion of *group_id*, returning its moodboard item.

    An image already on the board is tagged in place — never duplicated — so
    "Add Selected" can promote existing moodboard images straight into the
    set. Anything else is appended to the end of the group's strip, matching
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

    Reads the catalog's per-model ``supports_multi_view`` flag, which is the
    only source of truth — a hardcoded slug list used to back this up, but it
    listed the Tencent slugs and not the fal one that is actually enabled, so
    it hid the affordance for the one model that could use it. Before the
    catalog loads (offline / pre-auth) nothing is offered, which is correct:
    the job could not be submitted then either.
    """
    try:
        from mixar.modules.common.generation_params import (
            model_supports_multi_view,
        )
        return bool(model_supports_multi_view(service_key, model_slug))
    except Exception:
        return False


def build_active_group_payload(
    scene, image, service_key: str, model_slug: str
):
    """Build the active tab group's payload, or ``None`` without a set.

    An active set must never silently degrade to a single-image request.  Once
    companion views exist, an incapable/unknown catalog model is an error; the
    caller can surface it and cancel before spending credits.
    """
    group_id = get_active_group(scene)
    if not group_id:
        return None
    if not model_accepts_multi_view(service_key, model_slug):
        raise ValueError(
            f"'{model_slug}' does not accept multiple views — "
            "the active view set was not submitted"
        )

    from .turnaround_payload import build_multi_view_payload

    return build_multi_view_payload(scene, group_id, image, model_slug)


def allowed_view_types(model_slug: str) -> tuple:
    """Angles *model_slug* accepts.

    Hunyuan 3.0 and older take only left / right / back; top, bottom and the
    two three-quarter angles are 3.1-only. Unknown slugs get the full seven —
    under-restricting a future model is recoverable, over-restricting would
    silently drop panels the user supplied.
    """
    slug = (model_slug or "").strip().lower()
    if slug in TURNAROUND_BASE_ANGLE_ONLY_SLUGS:
        return TURNAROUND_VIEW_TYPES_V30
    return TURNAROUND_VIEW_ORDER


# ---------------------------------------------------------------------------
# Building a set from the moodboard selection
#
# The submit payload built from a finished set lives in
# :mod:`turnaround_payload` — kept in its own file for the 500-line limit.
# ---------------------------------------------------------------------------

def eligible_selected_images(scene, group_id: str, main_image) -> list:
    """Selected moodboard images that "Add Selected" would take.

    Everything currently selected on the board, minus what is already in the
    set and minus the Input Image itself (it is the frontal image, not a
    companion). Order follows the moodboard so the assignment of angles is
    predictable.
    """
    if not hasattr(scene, 'mixie_moodboard_images'):
        return []
    images = []
    for item in scene.mixie_moodboard_images:
        if not item.selected or not item.image:
            continue
        if item.image == main_image:
            continue
        if group_id and item.turnaround_group == group_id:
            continue
        images.append(item.image)
    return images


def add_images_as_views(
    scene, group_id: str, images: list, model_slug: str = ""
) -> Tuple[list, int]:
    """Attach *images* as companions, auto-assigning the next free angles.

    Returns ``(attached_view_types, skipped_for_capacity)``. Angles come from
    :func:`next_free_view_type` restricted to what *model_slug* accepts, so
    the default flow never produces a view the vendor will reject.
    """
    allowed = allowed_view_types(model_slug)
    attached: List[str] = []
    taken: List[str] = []
    skipped = 0
    for image in images:
        if len(group_items(scene, group_id)) >= TURNAROUND_MAX_COMPANIONS:
            skipped += 1
            continue
        view_type = next_free_view_type(
            scene, group_id, allowed=allowed, taken=taken)
        if not view_type:
            skipped += 1
            continue
        if attach_image(scene, group_id, image, view_type) is None:
            continue
        taken.append(view_type)
        attached.append(view_type)
    return attached, skipped


def group_summary(scene, group_id: str) -> Optional[str]:
    """``"3 of 7"`` for the section header, or None when there is no set."""
    items = group_items(scene, group_id)
    if not items:
        return None
    return f"{len(items)} of {TURNAROUND_MAX_COMPANIONS}"
