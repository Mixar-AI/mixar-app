# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Input images for the Image to 3D / Model Gen Generate operators.

Several selected moodboard stills queue one 3D job EACH: the reference strip
shows every selected still, so submitting only the first silently dropped the
rest. A companion view of a multi-view set whose frontal image is also
selected is not queued on its own — it rides that image's single multi-view
job.
"""

from .media_utils import selected_reference_stills


def selected_input_images(scene) -> list:
    """Distinct images of the selected moodboard stills, in board order."""
    from .turnaround_binding import group_id_for_main_image
    from .turnaround_views import find_group_for_image

    images = []
    for item in selected_reference_stills(scene):
        img = getattr(item, "image", None)
        if img is not None and img not in images:
            images.append(img)
    mains = {group_id_for_main_image(scene, img) for img in images} - {""}
    return [
        img for img in images
        if group_id_for_main_image(scene, img)
        or find_group_for_image(scene, img) not in mains
    ]


def tab_input_images(scene, tab) -> list:
    """Images one Generate press submits, one job each.

    Board-selection mode yields every selected still (empty when none);
    otherwise the tab's single uploaded ``reference_image`` (or nothing).
    """
    if getattr(tab, "use_selected_image", False):
        return selected_input_images(scene)
    image = getattr(tab, "reference_image", None)
    return [image] if image is not None else []
