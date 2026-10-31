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
read then: ``restore_original_materials`` runs right after every agent script.
"""

import bpy

# Every ID type whose datablock carries a ``materials`` list.
_DATA = ("meshes", "curves", "metaballs", "volumes", "pointclouds", "hair_curves", "grease_pencils")


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
