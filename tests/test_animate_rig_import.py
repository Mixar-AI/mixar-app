# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto Rig / Animate imports land as the skinned mesh + an Octahedral armature
shown In Front.

Production defect this pins: a Meshy-rigged import (fal-ai/meshy/rigging)
came in with a giant faceted Icosphere engulfing the character. The sphere
is not in the vendor's file — glTF has no bone custom shapes. Blender's own
glTF importer creates it by default (``disable_bone_shape=False``): an
"Icosphere" object in a hidden "glTF_not_exported" collection, assigned as
every bone's custom shape (which overrides the armature's Octahedral display)
and sized from the armature's extent, so a rig whose armature node carries a
small scale (a centimetre rig, 0.01) draws it ~100x oversized. The same rig
also imported with 10-36 m bones under the importer's BLENDER bone
heuristic, which divides each bone's length by the armature scale.

The fix is the import options alone, not post-import cleanup: nothing extra
is created, TEMPERANCE keeps the joint-to-joint bone lengths, and the
armature keeps Blender's default Octahedral display. The hooks stamp the
rig job id and turn the armature's In Front on, which the importer only sets
alongside the bone-shape Icosphere. Every Auto Rig entry point (Animate tab, agent, Moodboard
node) imports with the ONE ``ANIMATE_IMPORT_OPTIONS`` dict. Verified end to
end against the real Blender 5.2 importer (``bpy`` module): metre and
centimetre rigs both import as exactly Armature + mesh, no extra collection,
Octahedral 0.1 / 0.36 m bones, and baked animation deforms the mesh
identically under every bone heuristic.

``_rig_on_imported`` does ``import bpy`` INSIDE itself (this repo's lazy-
import convention), which re-resolves ``sys.modules["bpy"]`` at CALL time.
Patching must target that same live module object rather than a name bound
at this test file's collection time — some other test file in the full
suite run replaces the shared bpy mock, so a stale module-level reference
here would patch a different object than the one the function actually
reads, and every assertion below would silently check the wrong instance.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.hunyuan.constants import (
    ANIMATE_IMPORT_OPTIONS,
    ANIMATE_RIG_JOB_PROP,
)
from mixar.modules.hunyuan.core.animate_enqueue import (
    _animate_on_imported,
    _rig_on_imported,
)
from mixar.modules.moodboard.core import node_graph, node_mesh_execution

ANIMATE_ENQUEUE = (
    SCRIPTS / "mixar" / "modules" / "hunyuan" / "core" / "animate_enqueue.py"
)


class _FakeObject:
    """Minimal stand-in for a bpy.types.Object: attributes + ID-property
    item access (``obj["key"] = value``), which Blender objects support
    natively but SimpleNamespace does not."""

    def __init__(self, name, type='MESH'):
        self.name = name
        self.type = type
        self.data = SimpleNamespace(display_type='OCTAHEDRAL')
        self.show_in_front = False
        self._props = {}

    def __setitem__(self, key, value):
        self._props[key] = value

    def __getitem__(self, key):
        return self._props[key]

    def get(self, key, default=None):
        return self._props.get(key, default)


class _FakeObjectStore:
    """Name-keyed stand-in for bpy.data.objects with no ``remove``: a hook
    that tried to delete anything would fail the test."""

    def __init__(self, objects):
        self._objects = {o.name: o for o in objects}

    def get(self, name):
        return self._objects.get(name)


def _patch_objects(monkeypatch, objects):
    """Point the LIVE bpy module's data.objects at a fresh fake store."""
    monkeypatch.setattr(
        sys.modules["bpy"].data, "objects", _FakeObjectStore(objects)
    )


def _job(job_id="job-123"):
    return SimpleNamespace(backend_job_id=job_id)


def test_import_options_create_nothing_but_the_rig():
    assert ANIMATE_IMPORT_OPTIONS == {
        # No Icosphere / "glTF_not_exported" collection / bone custom shapes,
        # so bones draw with the armature's default Octahedral display.
        "disable_bone_shape": True,
        # Real joint-to-joint bone lengths at any armature scale.
        "bone_heuristic": "TEMPERANCE",
        # Non-Blender rigs: the glTF node transforms ARE the bind pose.
        "guess_original_bind_pose": False,
    }


def test_rig_import_is_stamped_octahedral_and_in_front(monkeypatch):
    armature = _FakeObject("Armature", type='ARMATURE')
    char_mesh = _FakeObject("char1", type='MESH')
    _patch_objects(monkeypatch, [armature, char_mesh])

    _rig_on_imported(_job(), "Armature, char1")

    assert armature[ANIMATE_RIG_JOB_PROP] == "job-123"
    assert char_mesh[ANIMATE_RIG_JOB_PROP] == "job-123"
    assert armature.data.display_type == 'OCTAHEDRAL'
    assert armature.show_in_front is True
    assert char_mesh.show_in_front is False  # only the armature


def test_pre_existing_object_is_never_touched(monkeypatch):
    mine = _FakeObject("UserRig", type='ARMATURE')
    imported = _FakeObject("Armature", type='ARMATURE')
    _patch_objects(monkeypatch, [mine, imported])

    _rig_on_imported(_job(), "Armature")

    assert imported[ANIMATE_RIG_JOB_PROP] == "job-123"
    assert imported.show_in_front is True
    assert mine.get(ANIMATE_RIG_JOB_PROP) is None
    assert mine.show_in_front is False


def test_animated_copy_is_in_front_without_a_rig_stamp(monkeypatch):
    armature = _FakeObject("Armature", type='ARMATURE')
    _patch_objects(monkeypatch, [armature])

    _animate_on_imported(_job(), "Armature")

    assert armature.show_in_front is True
    assert armature.get(ANIMATE_RIG_JOB_PROP) is None


def _enqueue_generation_keywords(function_name):
    tree = ast.parse(ANIMATE_ENQUEUE.read_text(encoding="utf-8"))
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    call = next(
        node for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "enqueue_generation"
    )
    return {
        kw.arg: kw.value.id
        for kw in call.keywords
        if isinstance(kw.value, ast.Name)
    }


def test_rig_and_animate_imports_share_the_options():
    rig = _enqueue_generation_keywords("enqueue_rig_jobs")
    animate = _enqueue_generation_keywords("enqueue_retarget_job")

    assert rig["import_options"] == "ANIMATE_IMPORT_OPTIONS"
    assert rig["on_imported"] == "_rig_on_imported"
    assert animate["import_options"] == "ANIMATE_IMPORT_OPTIONS"
    assert animate["on_imported"] == "_animate_on_imported"


def test_moodboard_auto_rig_node_imports_like_every_other_auto_rig():
    # The Moodboard Auto Rig node (and the Character Sheet workflow built on
    # it) submits through node_mesh_execution, not enqueue_rig_jobs; it once
    # carried its own stale copy of the options and still drew the Icosphere.
    routing = node_mesh_execution._MESH_FEATURE_ROUTING['AUTO_RIG']
    assert routing['import_options'] is ANIMATE_IMPORT_OPTIONS
    assert routing['armature_in_front'] is True
    for kind, other in node_mesh_execution._MESH_FEATURE_ROUTING.items():
        if kind != 'AUTO_RIG':
            assert not other.get('armature_in_front'), kind


def test_moodboard_auto_rig_result_hook_shows_the_armature_in_front(monkeypatch):
    armature = _FakeObject("Armature", type='ARMATURE')
    char_mesh = _FakeObject("char1", type='MESH')
    _patch_objects(monkeypatch, [armature, char_mesh])
    node = SimpleNamespace(node_id="rig-node")
    scene = SimpleNamespace(name="Scene")
    monkeypatch.setattr(
        node_mesh_execution.bpy.data, "scenes", {"Scene": scene}
    )
    monkeypatch.setattr(
        node_mesh_execution, "action_node_by_id", lambda _s, _id: node
    )
    results = []
    monkeypatch.setattr(
        node_graph, "create_asset_result",
        lambda s, n, names: results.append((s, n, names)),
    )

    hook = node_mesh_execution._mesh_result_hook(
        "Scene", "rig-node", armature_in_front=True
    )
    assert hook(_job(), "Armature, char1") == "Armature, char1"

    assert armature.show_in_front is True
    assert armature.data.display_type == 'OCTAHEDRAL'
    assert char_mesh.show_in_front is False
    assert results == [(scene, node, "Armature, char1")]


def test_moodboard_run_passes_the_routing_in_front_flag_to_the_hook():
    tree = ast.parse(
        (SCRIPTS / "mixar" / "modules" / "moodboard" / "core"
         / "node_mesh_execution.py").read_text(encoding="utf-8")
    )
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_mesh_feature"
    )
    call = next(
        node for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_mesh_result_hook"
    )
    flag = next(kw.value for kw in call.keywords if kw.arg == "armature_in_front")
    assert ast.unparse(flag) == "routing.get('armature_in_front', False)"
