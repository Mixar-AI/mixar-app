# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Import a local Gaussian-splat file (.spz or 3DGS .ply) into the scene.

Both formats go through Blender's own importers (``wm.spz_import`` and, for
3DGS PLY, ``wm.ply_import``), so no Python decoding runs. Mixar adds what the
stock importers lack: a ``Splat_*`` collection, the outliner stamps of
``splat_lifecycle`` and optional grounding at the origin — what the Director
flow needs to place cameras and characters inside a splat environment.

SPZ orientation depends on who wrote the file, and its header does not say:

* ``STANDARD`` — the SPZ spec's RUB frame (Niantic Scaniverse and most tools).
  ``wm.spz_import`` already lands these Z-up, so no rotation is added;
* ``WORLD_LABS`` — Marble files store the INRIA y-down frame, which
  ``wm.spz_import`` lands 180 deg about X from upright, so the object takes
  ``WORLD_LABS_SPZ_ROT_EULER_DEG``, the rotation generated worlds use too.

Must run on the main thread (it calls ``bpy.ops``).
"""

import os

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import rpt_
from mixar.modules.moodboard.core.splat_lifecycle import (
    finalize_splat_handles,
    note_splats_imported,
)
from mixar.modules.moodboard.core.splat_native import import_splat_spz, is_splat
from mixar.modules.moodboard.core.world_labs_importer import (
    _ensure_object_mode,
    _frame_objects,
    _import_splat_ply,
    _import_tracked,
    _move_to_collection,
    _orient_splats,
    _recenter_world_to_ground,
    RAW_PLY_ROT_EULER_DEG,
    WORLD_LABS_SPZ_ROT_EULER_DEG,
)

logger = get_logger(__name__)

SPLAT_EXTENSIONS = (".spz", ".ply")

SPZ_SOURCES = ("STANDARD", "WORLD_LABS")

#: Object rotation per SPZ source after ``wm.spz_import`` (see module doc).
_SPZ_ROT_EULER_DEG = {
    "STANDARD": (0.0, 0.0, 0.0),
    "WORLD_LABS": WORLD_LABS_SPZ_ROT_EULER_DEG,
}


def import_splat_file(
    filepath: str, name: str = "", recenter: bool = True, source: str = "STANDARD",
) -> list:
    """Import one ``.spz`` / 3DGS ``.ply`` file as a splat environment.

    Parameters
    ----------
    filepath : str
        Path to the splat file on disk.
    name : str, optional
        Collection name stem; defaults to the file name.
    recenter : bool
        Ground the splat (floor -> z=0, footprint centre -> origin) the same
        way generated World Labs worlds are grounded.
    source : str
        SPZ frame: ``"STANDARD"`` (spec RUB) or ``"WORLD_LABS"`` (Marble).
        Ignored for ``.ply``.

    Returns
    -------
    list[str]
        Names of the imported splat objects.

    Raises
    ------
    ValueError
        On unsupported extension, unreadable file, malformed SPZ, or a PLY
        that is not a Gaussian splat.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in SPLAT_EXTENSIONS:
        raise ValueError(rpt_("Unsupported splat file type '{ext}' (expected .spz or .ply)").format(
            ext=ext))
    if not os.path.isfile(filepath):
        raise ValueError(rpt_("File not found: {path}").format(path=filepath))

    if source not in SPZ_SOURCES:
        raise ValueError(rpt_("Unknown splat source '{source}'").format(source=source))

    stem = name or os.path.splitext(os.path.basename(filepath))[0] or "Splat"

    _ensure_object_mode()
    collection = _new_splat_collection(stem)

    try:
        if ext == ".spz":
            imported = _import_tracked(lambda: import_splat_spz(filepath))
        else:
            imported = _import_tracked(lambda: _import_splat_ply(filepath))
    except Exception:
        # A malformed file makes the native operator raise: leave no empty
        # Splat_* collection behind.
        bpy.data.collections.remove(collection)
        raise
    splat_objs = [obj for obj in imported if is_splat(obj)]
    if not splat_objs:
        # A PLY without the 3DGS fields comes in as an ordinary mesh: not ours.
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)
        raise ValueError(rpt_("{name} is not a Gaussian splat file").format(
            name=os.path.basename(filepath)))
    # A raw 3DGS .ply keeps the vendor y-DOWN frame (RAW_PLY_ROT_EULER_DEG);
    # SPZ is rotated per source (see module doc).
    _orient_splats(
        splat_objs,
        RAW_PLY_ROT_EULER_DEG if ext == ".ply" else _SPZ_ROT_EULER_DEG[source],
    )
    if recenter:
        _recenter_world_to_ground(splat_objs, [])

    _move_to_collection(splat_objs, collection)
    # Same outliner contract as a generated world (see splat_lifecycle).
    finalize_splat_handles(collection, splat_objs)
    _frame_objects(splat_objs)
    note_splats_imported()

    logger.info(
        "[SplatImport] imported '%s' (%s) into '%s' (%d splat)",
        os.path.basename(filepath), source if ext == ".spz" else "ply",
        collection.name, len(splat_objs),
    )
    return [o.name for o in splat_objs]


def _new_splat_collection(name: str) -> bpy.types.Collection:
    base = f"Splat_{name}"[:60]
    collection = bpy.data.collections.new(base)
    bpy.context.scene.collection.children.link(collection)
    return collection
