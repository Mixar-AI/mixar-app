# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source pins on the Assemble bpy adapter (bpy is a MagicMock outside Blender)."""

import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

from mixar.modules.common.utils import undo
from mixar.modules.moodboard.core import assemble_node, node_graph

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src/scripts/mixar/modules/moodboard/core"
SOURCE = (CORE / "assemble_node.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _assigned_attrs(nodes) -> set:
    return {
        target.attr
        for node in nodes for child in ast.walk(node) if isinstance(child, ast.Assign)
        for target in child.targets if isinstance(target, ast.Attribute)
    }


def test_success_pushes_one_named_undo_step():
    assert SOURCE.count('push_undo_step("Assemble Character")') == 1
    run = next(node for node in TREE.body
               if isinstance(node, ast.FunctionDef) and node.name == "run_assemble_node")
    body = ast.get_source_segment(SOURCE, run)
    # After the try/except: an exception never reaches the undo push.
    assert body.index("except Exception") < body.index("push_undo_step(")
    assert "snapshot.restore()" in body


def test_pose_position_restored_in_finally():
    finals = [node.finalbody for node in ast.walk(TREE) if isinstance(node, ast.Try)]
    assert any("pose_position" in _assigned_attrs(final) for final in finals)
    assert "pose_position = 'REST'" in SOURCE


def test_never_edits_mesh_data_names_or_uses_constraints():
    for banned in ("transform_apply", "CHILD_OF", ".data.transform(", ".name ="):
        assert banned not in SOURCE, banned
    # The parent inverse is only ever put back, by the rollback.
    writers = [node.name for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef)
               and "matrix_parent_inverse" in _assigned_attrs([node])]
    assert writers == ["restore"]


def test_writes_the_documented_stamps():
    for stamp in ("mixar_assembled_by", "mixar_assemble_rest", "mixar_attach",
                  "mixar_hidden_by"):
        assert f'"{stamp}"' in SOURCE
    assert 'root[STAMP_OWNER] = env["node_id"]' in SOURCE
    assert "root[STAMP_REST] = rest" in SOURCE


def test_bone_parent_keeps_world_matrix_and_uses_blender_52_api():
    for call in ("evaluated_get(depsgraph)", "to_mesh()", "to_mesh_clear()",
                 'foreach_get("co"', "BVHTree.FromObject(obj, depsgraph)",
                 "root.parent_type = 'BONE' if bone else 'OBJECT'",
                 "root.matrix_world = placed", "view_layer.update()"):
        assert call in SOURCE, call
    assert "Could not keep '{root.name}' in place while parenting" in SOURCE


def test_pure_modules_stay_bpy_free():
    for name in ("assemble_rules", "assemble_bones", "assemble_landmarks", "assemble_math"):
        text = (CORE / f"{name}.py").read_text(encoding="utf-8")
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(ast.parse(text))
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])
        }
        assert not imports & {"bpy", "mathutils", "bmesh"}, name


def test_every_new_engine_file_is_within_budget():
    budgets = {"assemble_rules": 250, "assemble_bones": 300, "assemble_landmarks": 200,
               "assemble_math": 450, "assemble_node": 450}
    for name, budget in budgets.items():
        lines = (CORE / f"{name}.py").read_text(encoding="utf-8").count("\n")
        assert lines <= budget, (name, lines)


# --------------------------------------------------------------------------- #
# Behaviour on a fake scene: world matrices only, so parenting keeps them as
# Blender's matrix_world setter does. Ray casts hit each object's ``boxes``.
# --------------------------------------------------------------------------- #

FIXTURE = ROOT / "tests/moodboard/fixtures/assemble_bones_mixamo.json"


def _box(lo, hi):
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


class _Mat:
    def __init__(self, rows):
        self.a = np.array(rows, dtype=float)

    def copy(self):
        return _Mat(self.a)

    def __array__(self, dtype=None, copy=None):
        return self.a.copy() if dtype is None else self.a.astype(dtype)


class _Obj(dict):
    __hash__ = object.__hash__
    __eq__ = object.__eq__

    def __init__(self, scene, name, kind, verts=(), parent=None):
        super().__init__()
        self.scene, self.name, self.type = scene, name, kind
        self._parent, self._parent_type, self._parent_bone = parent, 'OBJECT', ""
        self.mode, self.matrix_parent_inverse = 'OBJECT', _Mat(np.eye(4))
        self.matrix_world, self.hide_render, self.hidden = _Mat(np.eye(4)), False, False
        self.verts, self.modifiers, self.data, self.armature = np.array(verts), [], None, None
        self.boxes = []
        scene.objects.append(self)

    # Like RNA (ED_object_parent), every parent setter resets the parent inverse.
    def _relation(attr):
        def setter(self, value):
            setattr(self, attr, value)
            self.matrix_parent_inverse = _Mat(np.eye(4))
        return property(lambda self: getattr(self, attr), setter)

    parent = _relation("_parent")
    parent_type = _relation("_parent_type")
    parent_bone = _relation("_parent_bone")
    del _relation

    def as_pointer(self):
        return id(self)

    def hide_get(self, view_layer=None):
        return self.hidden

    def hide_set(self, state, view_layer=None):
        self.hidden = state

    def evaluated_get(self, depsgraph):
        return self

    def to_mesh(self):
        return NS(vertices=_Vertices(self.verts))

    def to_mesh_clear(self):
        pass

    def find_armature(self):
        return self.armature

    @property
    def children_recursive(self):
        out, frontier = [], [self]
        while frontier:
            children = [o for o in self.scene.objects if o.parent in frontier]
            out += children
            frontier = children
        return out

    def world_verts(self):
        return self.verts @ self.matrix_world.a[:3, :3].T + self.matrix_world.a[:3, 3]


class _Objects(list):
    def get(self, name):
        return next((obj for obj in self if obj.name == name), None)


class _Vertices(list):
    def foreach_get(self, attr, out):
        assert attr == "co"
        out[:] = np.asarray(self, dtype=float).reshape(-1)


@pytest.fixture
def rig(monkeypatch):
    scene = NS(objects=_Objects(), mixie_moodboard_links=[])
    pose_log = []
    bones = [NS(name=row["name"], head_local=row["head"], tail_local=row["tail"],
                parent=NS(name=row["parent"]) if row["parent"] else None,
                use_deform=row["deform"])
             for row in json.loads(FIXTURE.read_text(encoding="utf-8"))]

    class _ArmatureData:
        def __init__(self):
            self.bones, self._pose = bones, 'POSE'

        @property
        def pose_position(self):
            return self._pose

        @pose_position.setter
        def pose_position(self, value):
            pose_log.append(value)
            self._pose = value

    arm = _Obj(scene, "Armature", 'ARMATURE')
    arm.data = _ArmatureData()
    cloud = (_box((-0.15, -0.1, 0.9), (0.15, 0.1, 1.5)) + _box((-0.1, -0.1, 1.55), (0.1, 0.1, 1.8))
             + [(0.1, 0.0, 0.0), (-0.1, 0.0, 0.0), (0.6, 0.0, 0.95), (-0.6, 0.0, 0.95)])
    body = _Obj(scene, "Body", 'MESH', cloud, parent=arm)
    body.modifiers = [NS(type='ARMATURE', object=arm)]
    source = _Obj(scene, "Source Body", 'MESH', cloud)
    sword = [(x + 3.0, y, z) for x, y, z in _box((-0.015, -0.015, 0.0), (0.015, 0.015, 0.2))
             + _box((-0.025, -0.003, 0.2), (0.025, 0.003, 1.0))]
    talwar = _Obj(scene, "Talwar", 'MESH', sword)
    dhal = _Obj(scene, "Dhal", 'MESH', _box((-0.3, -0.03, 0.0), (0.3, 0.03, 0.6)))
    held = {"rig": ["Armature", "Body"], "p0": ["Talwar"], "p1": ["Dhal"], "p2": []}
    labels = {"rig": "Rig Body", "p0": "Talwar", "p1": "Dhal", "p2": "Left-hand item"}
    actions = {"rig": NS(action_type='AUTO_RIG'), "asm": NS(action_type='ASSEMBLE')}
    for index, (source_id, socket) in enumerate(
            (("rig", "body"), ("p0", "parts:0"), ("p1", "parts:1"), ("p2", "parts:2"))):
        scene.mixie_moodboard_links.append(NS(from_node_id=source_id, to_node_id="asm",
                                              to_socket=socket, input_order=index))
    results, undo_log = [], []
    monkeypatch.setattr(node_graph, "mesh_source_object_names",
                        lambda _scene, node_id: list(held.get(node_id, [])))
    monkeypatch.setattr(node_graph, "action_node_by_id", lambda _scene, node_id: actions.get(node_id))
    monkeypatch.setattr(node_graph, "input_source_object_names", lambda _scene, _n: ["Source Body"])
    monkeypatch.setattr(node_graph, "create_asset_result",
                        lambda _scene, _node, names: results.append(names))
    monkeypatch.setattr(assemble_node, "part_label", lambda _scene, node_id: labels[node_id])
    monkeypatch.setattr(assemble_node, "_matrix", _Mat)
    monkeypatch.setattr(undo, "push_undo_step", lambda message: undo_log.append(message))
    view_layer = NS(objects=scene.objects, update=lambda: None)
    context = NS(scene=scene, view_layer=view_layer, evaluated_depsgraph_get=lambda: None)
    node = NS(node_id="asm", action_type='ASSEMBLE', parameters=[], params_json="{}",
              state='DRAFT', edit_mode=True, error="")
    return NS(scene=scene, context=context, node=node, arm=arm, body=body, source=source,
              talwar=talwar, dhal=dhal, held=held, results=results, undo=undo_log,
              pose_log=pose_log, actions=actions, labels=labels)


def _state(obj):
    return (obj.parent.name if obj.parent else None, obj.parent_type, obj.parent_bone,
            obj.matrix_world.a.round(9).tolist(), dict(obj))


def test_assembles_on_bones_in_rest_pose_and_hides_the_source(rig):
    assemble_node.run_assemble_node(rig.context, rig.node)
    assert rig.pose_log == ['REST', 'POSE'] and rig.undo == ["Assemble Character"]
    assert (rig.talwar.parent, rig.talwar.parent_type, rig.talwar.parent_bone) == (
        rig.arm, 'BONE', "mixamorig:RightHand")
    assert rig.dhal.parent_bone == "mixamorig:LeftHand"
    # H = 1.8: the 5.7 cm hand bone is clamped to 0.04H, so the palm is 3.6 cm
    # down its 45-degree slope. The pommel centre sits 10% of the 0.936 m
    # talwar behind the palm, because the blade points -Y.
    palm = np.array([-0.55 - 0.025456, -0.02, 1.06 - 0.025456])
    pommel = rig.talwar.matrix_world.a @ [3.0, 0.0, 0.0, 1.0]
    assert np.allclose(pommel[:3], palm + [0.0, 0.0936, 0.0], atol=1e-5)
    assert rig.talwar["mixar_assembled_by"] == "asm"
    assert np.allclose(np.reshape(rig.talwar["mixar_assemble_rest"], (4, 4)), np.eye(4))
    assert json.loads(rig.talwar["mixar_attach"])["bone"] == "mixamorig:RightHand"
    assert rig.source.hidden and rig.source.hide_render and rig.source["mixar_hidden_by"] == "asm"
    assert not rig.body.hidden and rig.body.parent == rig.arm
    report = json.loads(rig.node.params_json)
    assert report["summary"] == "2 parts on bones, 1 skipped"
    assert [part["status"] for part in report["parts"]] == ["attached", "attached", "skipped"]
    assert report["parts"][0]["slot"] == 'HAND_R' and report["parts"][0]["bone_how"] == "name"
    assert report["parts"][2]["notes"] == ["not generated yet"]
    assert rig.results == ["Body, Armature, Talwar, Dhal"]
    assert (rig.node.state, rig.node.edit_mode, rig.node.error) == ('SUCCESS', False, "")


def test_rerun_is_idempotent(rig):
    assemble_node.run_assemble_node(rig.context, rig.node)
    first = [_state(obj) for obj in (rig.talwar, rig.dhal, rig.source)]
    assemble_node.run_assemble_node(rig.context, rig.node)
    assert [_state(obj) for obj in (rig.talwar, rig.dhal, rig.source)] == first
    assert rig.source.hidden
    # Disconnecting a part detaches it at its rest matrix on the next run.
    rig.scene.mixie_moodboard_links = [link for link in rig.scene.mixie_moodboard_links
                                       if link.from_node_id != "p1"]
    assemble_node.run_assemble_node(rig.context, rig.node)
    assert rig.dhal.parent is None and np.allclose(rig.dhal.matrix_world.a, np.eye(4))
    assert "mixar_assembled_by" not in rig.dhal


def test_failure_restores_every_object(rig, monkeypatch):
    # A Ctrl+P-parented source body: its parent inverse must survive the rollback.
    rig.source.parent = _Obj(rig.scene, "Plinth", 'MESH')
    inverse = np.diag([2.0, 2.0, 2.0, 1.0])
    rig.source.matrix_parent_inverse = _Mat(inverse)
    assemble_node.run_assemble_node(rig.context, rig.node)
    before = [_state(obj) for obj in (rig.talwar, rig.dhal, rig.source)]
    real = assemble_node.plan_part

    def failing(verts, settings, body, hit=None):
        if settings.slot == 'HAND_L':
            raise RuntimeError("boom")
        return real(verts, settings, body, hit)

    monkeypatch.setattr(assemble_node, "plan_part", failing)
    with pytest.raises(ValueError, match="boom"):
        assemble_node.run_assemble_node(rig.context, rig.node)
    assert [_state(obj) for obj in (rig.talwar, rig.dhal, rig.source)] == before
    assert rig.arm.data.pose_position == 'POSE' and rig.undo == ["Assemble Character"]
    assert np.array_equal(rig.source.matrix_parent_inverse.a, inverse)


def test_static_mode_and_refusals(rig):
    # An unrigged body (the rig card's result is a plain mesh): OBJECT parenting.
    rig.held["rig"] = ["Source Body"]
    assemble_node.run_assemble_node(rig.context, rig.node)
    assert rig.talwar.parent == rig.source and rig.talwar.parent_type == 'OBJECT'
    report = json.loads(rig.node.params_json)
    assert report["summary"] == "2 parts placed — not rigged, 1 skipped"
    assert report["parts"][0]["bone_how"] == "estimated" and not report["rigged"]
    rig.talwar.mode = 'EDIT'
    with pytest.raises(ValueError, match="Leave Pose/Edit mode first"):
        assemble_node.run_assemble_node(rig.context, rig.node)
    rig.scene.mixie_moodboard_links = rig.scene.mixie_moodboard_links[1:]
    with pytest.raises(ValueError, match="Connect a body to Assemble"):
        assemble_node.run_assemble_node(rig.context, rig.node)


def test_nested_part_meshes_move_with_their_root(rig):
    # A gem under its sword and a rigged prop (armature -> mesh): one root each.
    gem = _Obj(rig.scene, "Gem", 'MESH', _box((2.99, -0.01, 0.1), (3.01, 0.01, 0.12)),
               parent=rig.talwar)
    prop = _Obj(rig.scene, "Prop Rig", 'ARMATURE')
    _Obj(rig.scene, "Bow", 'MESH', _box((-0.02, -0.01, 0.0), (0.02, 0.01, 1.0)), parent=prop)
    rig.held.update(p0=["Talwar", "Gem"], p2=["Bow", "Prop Rig"])
    body_set = {rig.body, rig.arm}
    parts = assemble_node._resolve_parts(rig.scene, rig.node, body_set)
    assert [[root.name for root in part["roots"]] for part in parts] == [
        ["Talwar"], ["Dhal"], ["Prop Rig"]]
    assemble_node.run_assemble_node(rig.context, rig.node)
    assert gem.parent is rig.talwar and "mixar_assembled_by" not in gem
    assert rig.talwar.parent_bone == "mixamorig:RightHand" and prop.parent is rig.arm


def test_a_part_fed_by_another_assemble_card_is_refused(rig):
    rig.actions["other"] = NS(action_type='ASSEMBLE')
    rig.labels["other"] = "Assemble Character"
    rig.held["other"] = ["Armature", "Body", "Dhal"]
    rig.scene.mixie_moodboard_links[3].from_node_id = "other"
    assemble_node.run_assemble_node(rig.context, rig.node)
    part = json.loads(rig.node.params_json)["parts"][2]
    assert part["status"] == "skipped" and part["objects"] == []
    assert part["notes"] == ["connect the part's own card, not an Assemble card"]


def _ray_box(origin, direction, lo, hi):
    """The nearest t > 0 where the ray crosses an axis-aligned box's surface."""
    with np.errstate(divide="ignore", invalid="ignore"):
        near, far = (np.asarray(lo) - origin) / direction, (np.asarray(hi) - origin) / direction
    t_in = np.nanmax(np.minimum(near, far))
    t_out = np.nanmin(np.maximum(near, far))
    if t_in > t_out or t_out <= 1e-12:
        return None
    return t_in if t_in > 1e-12 else t_out


class _Tree:
    def __init__(self, boxes):
        self.boxes = boxes

    @classmethod
    def FromObject(cls, obj, _depsgraph):
        return cls(obj.boxes)

    def ray_cast(self, origin, direction):
        origin, direction = np.asarray(origin, dtype=float), np.asarray(direction, dtype=float)
        times = [t for lo, hi in self.boxes
                 if (t := _ray_box(origin, direction, lo, hi)) is not None]
        if not times:
            return (None, None, None, None)
        return (tuple(origin + direction * min(times)), None, 0, min(times))


def test_hip_ray_finds_the_pelvis_not_the_hanging_hand(rig, monkeypatch):
    # The A-pose left hand hangs beside the hips: a ray cast from outside would
    # stop on it and put the scabbard 0.5 m out. Cast from the hips bone, the
    # first crossing is the pelvis; the hand is past the layer gap.
    monkeypatch.setitem(sys.modules, "mathutils", NS(Vector=np.array))
    monkeypatch.setitem(sys.modules, "mathutils.bvhtree", NS(BVHTree=_Tree))
    rig.body.boxes = [((-0.15, -0.1, 0.9), (0.15, 0.1, 1.5)), ((-0.1, -0.1, 1.55), (0.1, 0.1, 1.8)),
                      ((0.53, -0.05, 0.94), (0.64, 0.01, 1.07))]
    scabbard = _Obj(rig.scene, "Scabbard", 'MESH', _box((4.97, -0.015, 0.0), (5.03, 0.015, 0.8)))
    rig.held["p2"], rig.labels["p2"] = ["Scabbard"], "Scabbard"
    assemble_node.run_assemble_node(rig.context, rig.node)
    part = json.loads(rig.node.params_json)["parts"][2]
    assert (part["slot"], part["bone"], part["notes"]) == ('HIP_L', "mixamorig:Hips", [])
    assert scabbard.parent_bone == "mixamorig:Hips"
    placed = scabbard.world_verts()
    # Pelvis surface x = 0.15, then a 0.0072 m gap: the sheath sits on the hip.
    assert placed[:, 0].min() == pytest.approx(0.15 + 0.004 * 1.8, abs=1e-6)
    assert placed[:, 0].max() < 0.53
