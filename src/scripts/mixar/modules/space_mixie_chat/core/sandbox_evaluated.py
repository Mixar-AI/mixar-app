# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Put back the original of every evaluated material an agent script stored.

``ob.evaluated_get(depsgraph).data.materials`` are the depsgraph's private
copies. Blender lets a script append one to a real mesh
(``me.materials.append(mat)``) or put it in a slot. The copy is freed at the
next re-evaluation, and the real mesh keeps a dangling pointer; the next
``new_from_object``, export or save segfaults. On uat4 (30 Oct), an AK-47
joined from 48 evaluated meshes crashed ``export_asset`` this way
(``foreach_libblock_make_usercounts_callback``).

The copies are still alive when the script returns, so their originals can be
read then: ``restore_original_materials`` runs right after an agent script
that could have handled evaluated data (``may_store_evaluated``). The scan
walks every material slot in the file, so a script that never named the
depsgraph or an evaluated datablock (most of them, every read-only one) skips it.
"""

import bpy

# Every ID type whose datablock carries a ``materials`` list.
_DATA = ("meshes", "curves", "metaballs", "volumes", "pointclouds", "hair_curves", "grease_pencils")

# A script reaches evaluated data only through one of these (lower-cased
# substrings): ``evaluated_get`` / ``evaluated_depsgraph_get`` / ``is_evaluated``
# / ``id_eval_get`` ("eval"), a depsgraph or its ``object_instances`` (also a
# handler's depsgraph argument, "handlers"), ``to_mesh`` / ``to_curve`` /
# ``new_from_object``, or ``.original``. Over-matching only costs a scan.
_EVALUATED_TOKENS = ("eval", "depsgraph", "object_instances", "handlers", "to_mesh", "to_curve",
                     "new_from_object", "original")


def may_store_evaluated(script) -> bool:
    """Whether ``script`` could have put an evaluated material in real data.
    True when the source is unavailable: then the scan runs."""
    if not isinstance(script, str) or not script:
        return True
    source = script.lower()
    return any(token in source for token in _EVALUATED_TOKENS)


def restore_original_materials() -> int:
    """Swap evaluated materials in real data and object slots for their
    originals; returns how many were swapped."""
    swapped = 0
    for name in _DATA:
        for data in getattr(bpy.data, name, ()):
            materials = getattr(data, "materials", None)
            if not materials:
                continue
            for index, material in enumerate(materials):
                if material is not None and material.is_evaluated:
                    materials[index] = material.original
                    swapped += 1
    for ob in bpy.data.objects:
        for slot in ob.material_slots:
            if slot.link == "OBJECT" and slot.material is not None and slot.material.is_evaluated:
                slot.material = slot.material.original
                swapped += 1
    return swapped


NOTE = ("Note: the script stored {count} evaluated material(s) (from evaluated_get(...).data) in real "
        "data; Mixar put back the originals. Use the original datablock (material.original), never one "
        "read from an evaluated object: the depsgraph frees its copies.")
