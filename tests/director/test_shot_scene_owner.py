# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A shot must not hold a refcounted pointer to its own scene.

``MixarDirectorShot`` used to carry ``scene_ref``, a ``PointerProperty`` to
``bpy.types.Scene``. RNA ID pointers are refcounted, so every shot added bumped
the Scene's user count and the topbar datablock selector grew a "2", "3", "4"
badge beside the scene name as the director added cameras. The shots collection
already lives on the scene, so ``id_data`` is the owner and costs nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core.shot_api import shot_scene

_MODULE = (
    Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules/director"
)


def _source(relative: str) -> str:
    return (_MODULE / relative).read_text(encoding="utf-8")


def test_shot_has_no_scene_pointer_property():
    """No Director PropertyGroup may point at a Scene."""
    source = _source("ui/properties/director_properties.py")
    assert "scene_ref" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "PointerProperty":
            continue
        for keyword in node.keywords:
            if keyword.arg != "type":
                continue
            # `type=bpy.types.Scene` is the shape that leaks the user count.
            assert ast.unparse(keyword.value) != "bpy.types.Scene"


def test_no_module_source_reads_scene_ref():
    """Every former `shot.scene_ref` reader goes through `shot_scene`."""
    for path in _MODULE.rglob("*.py"):
        assert "shot.scene_ref" not in path.read_text(encoding="utf-8"), path


def test_shot_scene_resolves_the_owning_scene():
    scene = SimpleNamespace(mixar_director=SimpleNamespace(shots=[]))
    shot = SimpleNamespace(id_data=scene)
    assert shot_scene(shot, None) is scene


def test_shot_scene_falls_back_when_the_owner_is_not_a_scene():
    """A detached/mocked shot still resolves to the caller's scene."""
    fallback = SimpleNamespace(mixar_director=SimpleNamespace(shots=[]))
    assert shot_scene(SimpleNamespace(), fallback) is fallback
    assert shot_scene(SimpleNamespace(id_data=None), fallback) is fallback
    # An owner that is some other ID (never the case in practice, but the
    # guard must not hand it back as a scene).
    assert shot_scene(SimpleNamespace(id_data=SimpleNamespace()), fallback) is fallback
