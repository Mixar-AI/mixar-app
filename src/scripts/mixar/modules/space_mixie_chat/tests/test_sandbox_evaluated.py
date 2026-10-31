# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An evaluated material an agent script stores in real data is swapped for
its original right after the script (sandbox_evaluated.py). Verified in the
app too: append an evaluated material, re-evaluate, ``new_from_object``
segfaulted before and survives now."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
sys.modules.setdefault("bpy", MagicMock())

from mixar.modules.space_mixie_chat.core import sandbox_evaluated as se  # noqa: E402


def _material(name, evaluated=False):
    original = SimpleNamespace(name=name, is_evaluated=False)
    original.original = original
    if not evaluated:
        return original
    return SimpleNamespace(name=name, is_evaluated=True, original=original)


def test_evaluated_materials_in_data_and_object_slots_become_originals(monkeypatch):
    steel, wood = _material("Steel", evaluated=True), _material("Wood")
    mesh = SimpleNamespace(materials=[steel, wood, None])
    curve = SimpleNamespace(materials=[_material("Paint", evaluated=True)])
    slot = SimpleNamespace(link="OBJECT", material=_material("Decal", evaluated=True))
    data_slot = SimpleNamespace(link="DATA", material=_material("Shared", evaluated=True))
    fake = SimpleNamespace(data=SimpleNamespace(
        meshes=[mesh], curves=[curve], metaballs=[], volumes=[], pointclouds=[],
        objects=[SimpleNamespace(material_slots=[slot, data_slot])]))
    monkeypatch.setattr(se, "bpy", fake)

    assert se.restore_original_materials() == 3
    assert mesh.materials[0] is steel.original and mesh.materials[1] is wood and mesh.materials[2] is None
    assert not curve.materials[0].is_evaluated
    assert not slot.material.is_evaluated
    # A DATA-linked slot shows the data's material: the data loop owns it.
    assert data_slot.material.is_evaluated


def test_nothing_to_swap_is_a_no_op(monkeypatch):
    fake = SimpleNamespace(data=SimpleNamespace(meshes=[SimpleNamespace(materials=[_material("A")])],
                                                objects=[]))
    monkeypatch.setattr(se, "bpy", fake)
    assert se.restore_original_materials() == 0
    assert "material.original" in se.NOTE.format(count=1)
