# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene geometry-cost probe and the handshake machine block.

Both exist because of the 2026-09-20 SIGKILLs: 1250 tree copies that shared two
mesh datablocks but carried per-object material links, which makes Cycles build
each one as its own mesh + BVH. The probe is what notices; the machine block is
what the budget is sized from.
"""

import sys

import pytest

from mixar.modules.common.agent_execution.scene_cost import (
    EMPTY_COST,
    LIBRARY_ASSET_PROP,
    breaks_instancing,
    cost_for_result,
    scene_geometry_cost,
)
from mixar.modules.space_mixie_chat.core import machine_info


class FakeMesh:
    def __init__(self, name, faces):
        self.name = name
        self.polygons = [None] * faces


class FakeSlot:
    def __init__(self, link="DATA"):
        self.link = link


class FakeModifier:
    def __init__(self, show_render=True):
        self.show_render = show_render


class FakeObject:
    def __init__(self, data=None, obj_type="MESH", slots=(), modifiers=(), props=None):
        self.data = data
        self.type = obj_type
        self.material_slots = list(slots)
        self.modifiers = list(modifiers)
        self._props = dict(props or {})

    def get(self, key, default=None):
        return self._props.get(key, default)


class FakeScene:
    def __init__(self, objects):
        self.objects = list(objects)


def _forest(count, mesh_faces=283_215, link="DATA", stamped=True):
    mesh = FakeMesh("tree", mesh_faces)
    props = {LIBRARY_ASSET_PROP: "broadleaf"} if stamped else None
    return [FakeObject(mesh, slots=[FakeSlot(), FakeSlot(link)], props=props)
            for _ in range(count)]


def test_shared_meshes_are_counted_once():
    """The whole point: 761 linked copies of one tree are ONE geometry."""
    cost = scene_geometry_cost(FakeScene(_forest(761)))
    assert cost["unique_faces"] == 283_215
    assert cost["objects"] == 761
    assert cost["meshes"] == 1
    assert cost["unique_objects"] == 0
    assert cost["library_instances"] == 761


def test_an_object_linked_material_makes_every_copy_its_own_mesh():
    """`material_slots[1].link='OBJECT'` sets matbits, which is what killed it."""
    cost = scene_geometry_cost(FakeScene(_forest(761, link="OBJECT")))
    assert cost["unique_objects"] == 761
    assert cost["meshes"] == 761
    assert cost["unique_faces"] == 761 * 283_215  # ~215M, the observed figure


def test_a_render_enabled_modifier_defeats_instancing_too():
    mesh = FakeMesh("rock", 1000)
    plain = FakeObject(mesh)
    modified = FakeObject(mesh, modifiers=[FakeModifier(show_render=True)])
    viewport_only = FakeObject(mesh, modifiers=[FakeModifier(show_render=False)])
    assert breaks_instancing(plain) is False
    assert breaks_instancing(modified) is True
    assert breaks_instancing(viewport_only) is False
    cost = scene_geometry_cost(FakeScene([plain, modified, viewport_only]))
    assert cost["unique_objects"] == 1
    assert cost["unique_faces"] == 2000  # the shared datablock once + the unique copy


def test_non_mesh_objects_count_as_objects_but_carry_no_faces():
    cost = scene_geometry_cost(FakeScene([
        FakeObject(None, obj_type="CAMERA"),
        FakeObject(None, obj_type="LIGHT"),
        FakeObject(FakeMesh("cube", 6)),
    ]))
    assert cost["objects"] == 3
    assert cost["meshes"] == 1
    assert cost["unique_faces"] == 6


def test_an_unreadable_scene_never_raises():
    assert scene_geometry_cost(object()) == EMPTY_COST
    assert scene_geometry_cost(FakeScene([object()]))["objects"] == 1


def test_only_an_effectful_successful_script_pays_for_the_measurement():
    scene = FakeScene(_forest(3))
    effectful = {"success": True, "created_objects": ["Tree"]}
    assert cost_for_result(scene, effectful)["objects"] == 3
    assert cost_for_result(scene, {"success": True}) is None            # read-only
    assert cost_for_result(scene, {"success": False,
                                   "created_objects": ["Tree"]}) is None  # failed
    assert cost_for_result(scene, None) is None


def test_deletions_count_as_effects():
    scene = FakeScene(_forest(2))
    assert cost_for_result(scene, {"success": True, "deleted_objects": ["Tree"]}) is not None


def test_the_probe_stays_cheap_for_a_big_scene():
    """3000 objects is an ordinary agent scene; measuring must be a plain loop."""
    import time

    scene = FakeScene(_forest(3000))
    started = time.monotonic()
    scene_geometry_cost(scene)
    assert time.monotonic() - started < 0.5


# ---------------------------------------------------------------------------
# The handshake machine block
# ---------------------------------------------------------------------------


def test_the_machine_block_reports_real_memory_on_this_host():
    block = machine_info.machine_block()
    assert set(block) == {"memory_bytes", "gpu_memory_bytes", "platform"}
    assert block["platform"] == sys.platform
    if sys.platform != "win32":
        assert block["memory_bytes"] > 1024**3  # this machine has more than 1 GB


def test_memory_is_none_rather_than_an_exception(monkeypatch):
    monkeypatch.setattr(machine_info.os, "sysconf",
                        lambda _name: (_ for _ in ()).throw(ValueError("no such name")))
    monkeypatch.setattr(machine_info.sys, "platform", "linux")
    assert machine_info.physical_memory_bytes() is None
    assert machine_info.machine_block()["memory_bytes"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX path under test")
def test_memory_is_pages_times_page_size(monkeypatch):
    monkeypatch.setattr(machine_info.sys, "platform", "darwin")
    monkeypatch.setattr(machine_info.os, "sysconf",
                        lambda name: {"SC_PHYS_PAGES": 4_194_304, "SC_PAGE_SIZE": 4096}[name])
    assert machine_info.physical_memory_bytes() == 17_179_869_184  # the 16 GB Mac


# ---------------------------------------------------------------------------
# The pump attaches the measurement to an effectful reply
# ---------------------------------------------------------------------------


def _pump_result(monkeypatch, scene, to_dict):
    from types import SimpleNamespace

    from mixar.modules.common.agent_execution import pump
    from mixar.modules.common.agent_execution.request import ExecutionRequest

    import bpy

    monkeypatch.setattr(bpy, "context", SimpleNamespace(scene=scene), raising=False)
    executor = SimpleNamespace(execute=lambda script: SimpleNamespace(to_dict=lambda: to_dict))
    req = ExecutionRequest("id-1", "pass", tool_name="execute_bpy_script")
    return pump.execute_request(req, executor)


def test_the_pump_measures_an_effectful_script(monkeypatch):
    result = _pump_result(monkeypatch, FakeScene(_forest(4)),
                          {"success": True, "created_objects": ["Tree"]})
    assert result["scene_cost"]["objects"] == 4
    assert result["scene_cost"]["unique_faces"] == 283_215


def test_the_pump_leaves_a_read_only_script_alone(monkeypatch):
    result = _pump_result(monkeypatch, FakeScene(_forest(4)), {"success": True})
    assert "scene_cost" not in result


def test_a_probe_failure_never_changes_the_outcome(monkeypatch):
    result = _pump_result(monkeypatch, None, {"success": True, "created_objects": ["Tree"]})
    assert result["success"] is True
    assert "scene_cost" not in result
