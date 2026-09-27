# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""No-credit QA scenario: an Auto Rig result imports as mesh + Octahedral armature, In Front.

Builds a centimetre-scale skinned character (armature node scaled 0.01, the
case that drew a giant Icosphere and 10-36 m bones), round-trips it through
GLB, and imports it exactly as the queue does for Auto Rig results
(``model_io.import_file`` + ``ANIMATE_IMPORT_OPTIONS`` + ``_rig_on_imported``).
Every Auto Rig entry point — the Animate tab, the agent, and the Moodboard
Auto Rig node — imports with that one options dict.

Launch a fresh isolated app with $QA_HARNESS/run_qa_app.sh, then run:
    QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/rig_import_display_e2e.py
Uses MIXAR_QA_PORT and QA_SCENARIO_OUT when set. Never run on a user session.
Vision: the snapshot must show the cylinder character with normal Octahedral
bones drawn over it (In Front), and no sphere or oversized bones.
"""

import os
from pathlib import Path
import sys
import tempfile
import textwrap

# The SETUP / CHECK snippets use only ``bpy`` and Mixar modules, so they also
# run under Blender's ``bpy`` module outside the app.
SETUP = '''
import bmesh, os, tempfile
from types import SimpleNamespace
from mathutils import Matrix, Vector
from mixar.modules.common.job_queue.core.model_io import import_file
from mixar.modules.hunyuan.constants import ANIMATE_IMPORT_OPTIONS
from mixar.modules.hunyuan.core.animate_enqueue import _rig_on_imported
from mixar.modules.moodboard.core.node_mesh_execution import _MESH_FEATURE_ROUTING
assert _MESH_FEATURE_ROUTING["AUTO_RIG"]["import_options"] is ANIMATE_IMPORT_OPTIONS
assert "QA_Rig" not in bpy.data.objects, "Start a fresh QA instance"
scene = bpy.context.scene
arm = bpy.data.objects.new("QA_Rig", bpy.data.armatures.new("QA_Rig"))
scene.collection.objects.link(arm)
arm.scale = (0.01, 0.01, 0.01)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
joints = {
    "Hips": ((0, 0, 90), (0, 0, 100), None),
    "Spine": ((0, 0, 100), (0, 0, 140), "Hips"),
    "Head": ((0, 0, 140), (0, 0, 175), "Spine"),
    "LeftArm": ((10, 0, 135), (70, 0, 135), "Spine"),
    "RightArm": ((-10, 0, 135), (-70, 0, 135), "Spine"),
    "LeftLeg": ((10, 0, 90), (10, 0, 0), "Hips"),
    "RightLeg": ((-10, 0, 90), (-10, 0, 0), "Hips"),
}
for name, (head, tail, parent) in joints.items():
    bone = arm.data.edit_bones.new(name)
    bone.head, bone.tail = Vector(head), Vector(tail)
    if parent:
        bone.parent = arm.data.edit_bones[parent]
bpy.ops.object.mode_set(mode="OBJECT")
mesh = bpy.data.meshes.new("QA_Body")
body = bpy.data.objects.new("QA_Body", mesh)
scene.collection.objects.link(body)
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.25, radius2=0.25,
                      depth=1.8, matrix=Matrix.Translation((0, 0, 0.9)))
bm.to_mesh(mesh)
bm.free()
spine = body.vertex_groups.new(name="Spine")
spine.add([v.index for v in mesh.vertices], 1.0, "REPLACE")
body.parent = arm
body.matrix_parent_inverse = arm.matrix_world.inverted()
body.modifiers.new("Armature", "ARMATURE").object = arm
for obj in bpy.data.objects:
    obj.select_set(obj in (arm, body))
glb = os.path.join(tempfile.mkdtemp(prefix="mixar-rig-qa-"), "rig.glb")
bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True)
for obj in (body, arm):
    data = obj.data
    bpy.data.objects.remove(obj)
    (bpy.data.meshes if data.__class__.__name__ == "Mesh" else bpy.data.armatures).remove(data)
names = import_file(glb, "GLB", ANIMATE_IMPORT_OPTIONS)
_rig_on_imported(SimpleNamespace(backend_job_id="qa-rig-job"), names)
bpy.context.scene["qa_rig_import_names"] = names
result = True
'''

CHECK = '''
from mixar.modules.hunyuan.constants import ANIMATE_RIG_JOB_PROP
names = [n.strip() for n in bpy.context.scene["qa_rig_import_names"].split(",")]
objs = [bpy.data.objects[n] for n in names]
assert sorted(o.type for o in objs) == ["ARMATURE", "MESH"], names
assert "glTF_not_exported" not in bpy.data.collections
assert not [o for o in bpy.data.objects if o.name.startswith("Icosphere")]
arm = next(o for o in objs if o.type == "ARMATURE")
body = next(o for o in objs if o.type == "MESH")
assert arm.data.display_type == "OCTAHEDRAL"
assert arm.show_in_front
assert not any(b.custom_shape for b in arm.pose.bones)
scale = arm.matrix_world.to_scale().x
height = body.dimensions.z
assert abs(height - 1.8) < 0.01, height
for bone in arm.data.bones:
    length = bone.length * scale
    assert 0.0 < length < 0.5 * height, (bone.name, length)
assert max(arm.dimensions) < height, arm.dimensions
assert any(m.type == "ARMATURE" and m.object == arm for m in body.modifiers)
assert arm[ANIMATE_RIG_JOB_PROP] == body[ANIMATE_RIG_JOB_PROP] == "qa-rig-job"
result = True
'''

FRAME = '''
names = [n.strip() for n in bpy.context.scene["qa_rig_import_names"].split(",")]
for obj in bpy.context.view_layer.objects:
    obj.select_set(obj.name in names)
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == "VIEW_3D")
region = next(r for r in area.regions if r.type == "WINDOW")
area.spaces.active.shading.type = "SOLID"
with bpy.context.temp_override(window=w, area=area, region=region):
    bpy.ops.view3d.view_axis(type="FRONT")
    bpy.ops.view3d.view_selected()
result = True
'''


def evaluate(qa, code):
    assert qa.eval(textwrap.dedent(code)) is True


def run(qa):
    out = Path(os.environ.get("QA_SCENARIO_OUT", tempfile.mkdtemp(prefix="mixar-rig-qa-")))
    out.mkdir(parents=True, exist_ok=True)
    evaluate(qa, 'import os; assert os.environ.get("MIXAR_QA") == "1"; result=True')
    qa.wait("any(a.type == 'VIEW_3D' for a in drv.main_window().screen.areas)", timeout=60)
    qa.step("import a centimetre rig the way Auto Rig does", evaluate, qa, SETUP)
    qa.step("only mesh + Octahedral armature landed", evaluate, qa, CHECK)
    qa.step("frame the import", evaluate, qa, FRAME)
    snap = str(out / "rig-import-octahedral.png")
    qa.cmd("snap", path=snap, area="VIEW_3D")
    return {"snapshots": [snap], "credits_spent": 0}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
    from lib import run_scenario

    run_scenario("rig_import_display", run)
