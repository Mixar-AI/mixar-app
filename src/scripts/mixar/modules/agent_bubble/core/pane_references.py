# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Attach an image file as the ACTIVE generation pane's reference.

One routing table shared by every way a still reaches a pane — the
viewport capture (``mixar.pane_capture_viewport``) and the clipboard paste
(``mixie_chat.paste_image`` while the island shows a generation tab) — so
both land exactly where that pane's own upload puts it:

* 3D     -> ``tab_image_to_3d.reference_image``, ``use_selected_image`` off
  (what ``mixie.image_to_3d_upload_image`` does).
* Image  -> ``tab_imagegen.reference_images`` (the add
  ``mixie.imagegen_upload_reference`` performs: packed image, boarded
  unselected, mirrored into the tab's reference collection).
* Video  -> boarded as a SELECTED moodboard item — Video Gen's references
  ARE the selected board media (``get_selected_moodboard_media_inputs``).
* Gaussian Splat -> ``tab_world_labs.reference_image`` with
  ``use_selected_image`` off so the attached still is what submits.

Every other tab (Agent, Library, Queue) is not a pane: callers keep their
own chat-attachment path for it.
"""

import os

PANE_TABS = frozenset({'THREE_D', 'IMAGE', 'VIDEO', 'SPLAT'})


def attach_to_imagegen(scene, img, filepath):
    """The exact reference-add mixie.imagegen_upload_reference performs."""
    from mixar.modules.moodboard.core.moodboard_utils import (
        place_new_moodboard_item,
    )

    tab = scene.mixie_moodboard_sidebar.tab_imagegen

    mb_item = scene.mixie_moodboard_images.add()
    mb_item.image = img
    mb_item.scale = 1.0
    place_new_moodboard_item(scene, mb_item)
    mb_item.selected = False

    ref_item = tab.reference_images.add()
    ref_item.image = img
    ref_item.moodboard_index = len(scene.mixie_moodboard_images) - 1
    ref_item.display_name = img.name
    if img.size[0] > 0 and img.size[1] > 0:
        ref_item.display_resolution = f"{img.size[0]} x {img.size[1]}"
    else:
        ref_item.display_resolution = "Unknown"
    ref_item.display_path = filepath
    if hasattr(tab, "use_reference_images"):
        # Uploaded/captured refs are used with board-selection mode OFF.
        tab.use_reference_images = False


def attach_to_board_selected(scene, filepath):
    """Board the file as a SELECTED item (Video Gen's reference source)."""
    from mixar.modules.moodboard.core.media_import import (
        load_media_file_to_board,
    )

    item = load_media_file_to_board(scene, filepath)
    if item is not None:
        item.selected = True
    return item


def _load_packed(filepath, image_name):
    import bpy

    img = bpy.data.images.load(filepath, check_existing=False)
    img.name = image_name or os.path.basename(filepath)
    img.pack()
    return img


def attach_file_to_pane(scene, pane_tab, filepath, image_name=""):
    """Attach ``filepath`` as ``pane_tab``'s reference.

    Raises on failure (callers report it). ``pane_tab`` must be one of
    ``PANE_TABS``.
    """
    if pane_tab not in PANE_TABS:
        raise ValueError(f"not a generation pane: {pane_tab!r}")
    sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
    if sidebar is None:
        raise RuntimeError("moodboard sidebar properties unavailable")

    if pane_tab == 'VIDEO':
        if attach_to_board_selected(scene, filepath) is None:
            raise RuntimeError("could not add the image to the moodboard")
        return

    img = _load_packed(filepath, image_name)
    if pane_tab == 'IMAGE':
        attach_to_imagegen(scene, img, filepath)
        return
    owner = sidebar.tab_image_to_3d if pane_tab == 'THREE_D' else sidebar.tab_world_labs
    owner.reference_image = img
    if hasattr(owner, "use_selected_image"):
        owner.use_selected_image = False


def redraw_bubbles(window_manager):
    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'AGENT_BUBBLE':
                area.tag_redraw()
