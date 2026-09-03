# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A generated mesh must still be findable after its post-import rename.

``imported_object_names`` is a job's only handle on what it put in the scene,
and consumers resolve it through ``bpy.data.objects.get()``. Every Model Gen
path attaches an ``on_imported`` hook that RENAMES the import, which freed the
name ``Job.on_imported`` had just recorded — so the generations-library
archiver looked the mesh up by a dead name, found nothing, and silently
archived none of them (``[GenLibrary] No mesh to archive``).

The contract these pin: a renaming hook returns its final name, and
``AsyncGLBJob.on_imported`` records that instead.
"""

import sys
import types
from pathlib import Path

from mixar.modules.asset_search.core import generation_library as gl
from mixar.modules.common.job_queue.core.generic_jobs import AsyncGLBJob

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/scripts/mixar/modules"


# --------------------------------------------------------------------------- #
# A mutable stand-in for bpy.data.objects — renaming re-keys the datablock,
# exactly as Blender does, so a stale lookup really misses.
# --------------------------------------------------------------------------- #

class _FakeObjects:
    def __init__(self):
        self._by_name = {}

    def add(self, obj):
        self._by_name[obj.name] = obj
        return obj

    def get(self, name):
        return self._by_name.get(name)

    def rename(self, old, new):
        obj = self._by_name.pop(old)
        obj._name = new
        self._by_name[new] = obj

    def names(self):
        return sorted(self._by_name)


class _FakeObject:
    def __init__(self, name, type_="MESH", polys=500):
        self._name = name
        self.type = type_
        self.data = types.SimpleNamespace(polygons=[None] * polys) if type_ == "MESH" else None

    @property
    def name(self):
        return self._name


# --------------------------------------------------------------------------- #
# The mechanism: AsyncGLBJob.on_imported
# --------------------------------------------------------------------------- #

def test_renaming_hook_repoints_the_job_at_the_final_name():
    job = AsyncGLBJob(feature_key="model_3d")
    job._on_imported_hook = lambda _job, _names: "hero_chair"

    job.on_imported("world")

    assert job.imported_object_names == "hero_chair"


def test_non_renaming_hook_keeps_the_imported_names():
    """Inspect-only hooks (the rig stamper, the segment grouper) return None."""
    seen = []
    job = AsyncGLBJob(feature_key="animate")
    job._on_imported_hook = lambda _job, names: seen.append(names)  # returns None

    job.on_imported("Armature, Body")

    assert seen == ["Armature, Body"]
    assert job.imported_object_names == "Armature, Body"


def test_no_hook_keeps_the_imported_names():
    job = AsyncGLBJob(feature_key="model_3d")

    job.on_imported("world")

    assert job.imported_object_names == "world"


def test_a_failing_hook_leaves_the_imported_names_intact():
    """The hook raised before renaming, so the original names still resolve."""
    def _boom(_job, _names):
        raise RuntimeError("post-import processing failed")

    job = AsyncGLBJob(feature_key="model_3d")
    job._on_imported_hook = _boom

    job.on_imported("world")

    assert job.imported_object_names == "world"


def test_blank_hook_return_is_ignored():
    """rename_generated_model returns None when it finds no mesh — never let
    that blank out the only handle the job has on its import."""
    for blank in (None, "", "   ", 0, []):
        job = AsyncGLBJob(feature_key="model_3d")
        job._on_imported_hook = lambda _job, _names, b=blank: b

        job.on_imported("world")

        assert job.imported_object_names == "world", blank


# --------------------------------------------------------------------------- #
# End to end: the archiver finds the mesh the Model Gen flow produced
# --------------------------------------------------------------------------- #

def _replay_model_gen_import(monkeypatch, objects, imported_names, target):
    """Replay queue_download._finish_import's ordering for one GLB."""
    monkeypatch.setattr(
        gl, "bpy", types.SimpleNamespace(data=types.SimpleNamespace(objects=objects))
    )

    job = AsyncGLBJob(feature_key="model_3d", label="hero chair")
    job.job_type = "model_3d"

    def _renaming_hook(_job, names):
        # Stands in for make_model_rename_on_imported -> rename_generated_model.
        first = names.split(",")[0].strip()
        objects.rename(first, target)
        return target

    job._on_imported_hook = _renaming_hook
    job.on_imported(imported_names)  # <- the rename happens in here
    return job


def test_archiver_finds_the_mesh_after_the_model_gen_rename(monkeypatch):
    objects = _FakeObjects()
    objects.add(_FakeObject("world"))  # the name the GLB carried

    job = _replay_model_gen_import(monkeypatch, objects, "world", "hero_chair")

    assert objects.names() == ["hero_chair"]  # "world" is gone
    mesh = gl._pick_mesh(job.imported_object_names)
    assert mesh is not None and mesh.name == "hero_chair"


def test_archiver_qualifies_that_job(monkeypatch):
    """Guard the other half: resolving the mesh is useless if the job is
    filtered out before _pick_mesh is ever reached."""
    objects = _FakeObjects()
    objects.add(_FakeObject("world"))

    job = _replay_model_gen_import(monkeypatch, objects, "world", "hero_chair")

    assert gl._is_qualifying(job)
    assert (job.imported_object_names or "").strip()  # the listener's own gate


def test_archiver_skips_the_empty_of_a_trellis_assembly(monkeypatch):
    """Trellis returns a mesh parented to an Empty and rename_generated_model
    returns the MESH name — the archiver must never pick the Empty."""
    objects = _FakeObjects()
    objects.add(_FakeObject("world", type_="EMPTY"))
    objects.add(_FakeObject("mesh_0"))

    monkeypatch.setattr(
        gl, "bpy", types.SimpleNamespace(data=types.SimpleNamespace(objects=objects))
    )
    objects.rename("mesh_0", "hero_chair")
    objects.rename("world", "empty_hero_chair")

    mesh = gl._pick_mesh("hero_chair")
    assert mesh is not None and mesh.type == "MESH"


# --------------------------------------------------------------------------- #
# Source guard: a new renaming hook must not silently regress this
# --------------------------------------------------------------------------- #

RENAMING_HOOKS = (
    # (file, function that renames, the call whose result must be returned)
    ("moodboard/core/generation_enqueue.py", "make_model_rename_on_imported"),
    ("moodboard/core/generation_enqueue.py", "make_texture_reimport_on_imported"),
    ("moodboard/core/generation_enqueue.py", "_make_hp_on_imported"),
    ("moodboard/core/generation_enqueue.py", "_make_lp_on_imported"),
    ("moodboard/core/node_execution.py", "_result_hook"),
    ("moodboard/core/node_execution.py", "_mesh_result_hook"),
    ("hunyuan/core/retopology_enqueue.py", "_retopology_on_imported"),
    ("hunyuan/core/retopology_enqueue.py", "_make_tripo_on_imported"),
)


def _hook_source(rel_path, func_name):
    text = (SCRIPTS / rel_path).read_text(encoding="utf-8")
    start = text.index(f"def {func_name}(")
    rest = text[start:]
    # Up to the next top-level def, which is where this hook's body ends.
    end = rest.find("\ndef ", 1)
    return rest if end == -1 else rest[:end]


def test_every_renaming_hook_hands_its_final_name_back():
    for rel_path, func_name in RENAMING_HOOKS:
        source = _hook_source(rel_path, func_name)
        assert "return final" in source or "return result" in source, (
            f"{rel_path}:{func_name} renames its import but returns nothing — "
            "the job would keep pointing at a freed object name"
        )
