# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thumbnail backfill: write rendered previews back into their source .blend.

Assets that had NO usable embedded preview were rendered during training;
saving that render as their preview gives them a real thumbnail in the island
Library and Blender's Asset Browser, and lets the next training run of an
object take the fast reuse path. Materials get their sphere view (see
``material_preview.THUMBNAIL_VIEW``) and are still rendered on every train.

DELIBERATELY self-contained (bpy + numpy + stdlib only): the headless preview
worker imports it from this directory under ``--factory-startup``, where no
``mixar`` package exists.
"""

import os

import bpy


def apply_preview_from_jpg(datablock, jpg_path):
    """Load a JPEG and set it as ``datablock``'s embedded preview."""
    import numpy as np
    img = bpy.data.images.load(jpg_path)
    try:
        w, h = img.size
        if not (w and h):
            return False
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        preview = datablock.preview_ensure()
        preview.image_size = (w, h)
        preview.image_pixels_float.foreach_set(buf)
        return True
    finally:
        bpy.data.images.remove(img)


def _datablock(entry):
    # By kind: a material may share its name with an object.
    if entry.get("kind") == "MATERIAL":
        return bpy.data.materials.get(entry["name"])
    return bpy.data.objects.get(entry["name"]) or bpy.data.collections.get(entry["name"])


def backfill_previews(entries, heartbeat):
    """Write each entry's JPEG into its .blend as the asset's preview.

    Groups by .blend (one open + save per file); Blender's save writes via a
    temp file, so a killed worker can't corrupt a library. ``heartbeat()`` is
    called per file to keep the parent's stall watchdog fed.
    """
    by_blend = {}
    for e in entries:
        by_blend.setdefault(e["blend_str"], []).append(e)

    for blend_path, blend_entries in by_blend.items():
        heartbeat()
        try:
            bpy.ops.wm.open_mainfile(filepath=blend_path, load_ui=False)
        except Exception as exc:  # noqa: BLE001 — skip unopenable files
            print(f"[backfill] cannot open {blend_path}: {exc}")
            continue
        changed = False
        for e in blend_entries:
            datablock = _datablock(e)
            if datablock is None or not os.path.isfile(e["jpg"]):
                continue
            try:
                if apply_preview_from_jpg(datablock, e["jpg"]):
                    changed = True
            except Exception as exc:  # noqa: BLE001
                print(f"[backfill] preview failed for {e['name']}: {exc}")
        if changed:
            try:
                bpy.ops.wm.save_mainfile(filepath=blend_path)
                print(f"[backfill] saved previews into {blend_path}")
            except Exception as exc:  # noqa: BLE001
                print(f"[backfill] cannot save {blend_path}: {exc}")
