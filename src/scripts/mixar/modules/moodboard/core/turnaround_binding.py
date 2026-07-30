# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Set ⇄ Frontal Image Binding

``item.turnaround_main_group`` is the ONLY link between a multi-view set and
an image. A set is submitted alongside an image if, and only if, the image
being converted carries the set's id here.

**Invariant:** for any group id exactly one moodboard item carries it, and
that item is the set's frontal (main) image — never one of its companions.
Every operator that creates, re-points or empties a set has to maintain that,
which is why the maintenance primitives live together in one small module.

Why a second property instead of putting the main into ``turnaround_group``:
that property means "companion of", and ``group_items`` /
``eligible_selected_images`` / the vendor's 7-companion cap / the panel's view
list all iterate on it. Adding the frontal image would make it a companion of
its own set.

Split out of :mod:`turnaround_views` for the 500-line limit; re-exported from
there, so ``from .turnaround_views import group_id_for_main_image`` keeps
working. ``group_items`` is imported lazily inside the two functions that
need it — ``turnaround_views`` imports this module at module level, so a
top-level import back would be circular.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def group_id_for_main_image(scene, image) -> str:
    """The multi-view group *image* is the frontal image of, or "".

    Answers "" for companions, for ordinary board images and for a set whose
    companions have all been removed — the same self-healing emptiness check
    ``get_active_group`` does, so a hollowed-out set reports as absent instead
    of failing at payload build.
    """
    from .turnaround_views import group_items

    if image is None or not hasattr(scene, 'mixie_moodboard_images'):
        return ""
    for item in scene.mixie_moodboard_images:
        if item.image != image:
            continue
        group_id = getattr(item, 'turnaround_main_group', '') or ""
        if group_id and group_items(scene, group_id):
            return group_id
    return ""


def main_image_item(scene, group_id: str):
    """The moodboard item marked as *group_id*'s frontal image, or None."""
    if not group_id or not hasattr(scene, 'mixie_moodboard_images'):
        return None
    for item in scene.mixie_moodboard_images:
        if (getattr(item, 'turnaround_main_group', '') or "") == group_id:
            return item
    return None


def clear_group_main(scene, group_id: str) -> None:
    """Unbind *group_id* from whatever image currently claims to be its main."""
    if not group_id or not hasattr(scene, 'mixie_moodboard_images'):
        return
    for item in scene.mixie_moodboard_images:
        if (getattr(item, 'turnaround_main_group', '') or "") == group_id:
            item.turnaround_main_group = ""


def set_group_main_image(scene, group_id: str, image) -> bool:
    """Bind *group_id* to *image*, which becomes the set's frontal image.

    Any previous main is unbound first, so the one-main-per-group invariant
    holds however the set was assembled or re-pointed. Returns False when
    *image* is not on the moodboard — a file-picked reference image cannot
    carry the marker, so such a set stays unbound (and therefore inert)
    rather than silently attaching itself to the wrong image.
    """
    from .turnaround_views import moodboard_item_for

    if not group_id or image is None:
        return False
    item = moodboard_item_for(scene, image)
    if item is None:
        return False
    clear_group_main(scene, group_id)
    item.turnaround_main_group = group_id
    return True


def forget_main_if_empty(scene, group_id: str) -> None:
    """Drop the main marker once *group_id* has no companions left.

    Without this, removing the last view leaves the frontal image still
    claiming to own a set — and the next generation from it would raise on an
    incapable model over a set that no longer exists.
    """
    from .turnaround_views import group_items

    if group_id and not group_items(scene, group_id):
        clear_group_main(scene, group_id)
