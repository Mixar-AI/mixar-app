# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""No-credit QA scenario for Blender 5.2 paint animation and tab filters.

Launch a fresh isolated app with $QA_HARNESS/run_qa_app.sh, then run:
    QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/blender52_regressions_e2e.py
Uses MIXAR_QA_PORT and QA_SCENARIO_OUT when set. Never run on a user session.
"""

import os
from pathlib import Path
import sys
import tempfile
import textwrap

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario


SETUP = '''
import os
assert os.environ.get("MIXAR_QA") == "1", "Requires an isolated QA app"
assert bpy.data.node_groups.get("QA_Paint") is None, "Start a fresh QA instance"
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == "MIXIE")
area.type = "MIXAR_LAYERS"
props = next(a for a in w.screen.areas if a.type == "OUTLINER")
props.type = "PROPERTIES"
with bpy.context.temp_override(window=w, area=area):
    assert bpy.ops.layers.create_material(
        tree_name="QA_Paint", ao=False, switch_to_material_view=False
    ) == {"FINISHED"}
from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node
from mixar.modules.paint.utils.common_entity import get_entity_prop_input
from mixar.modules.common.utils.animation import assigned_fcurves
tree = get_active_mpaint_node().node_tree
tree.name = "QA_Paint"
layer = tree.mp.layers[0]
layer.name = "QA Animated Fill"
socket = get_entity_prop_input(layer, "intensity_value")
for frame, value in ((1, 0.25), (20, 0.75)):
    socket.default_value = value
    socket.keyframe_insert("default_value", frame=frame)
curve = assigned_fcurves(tree)[0]
assert len(curve.keyframe_points) == 2
result = True
'''

COPY_AND_SHARED_SLOT = '''
from mixar.modules.common.utils.animation import assigned_fcurves
from mixar.modules.paint.core.node.node_copy_utils import copy_fcurves
from mixar.modules.paint.utils.common_animation import get_material_fcurves
tree = bpy.data.node_groups["QA_Paint"]
source = assigned_fcurves(tree)[0]
dest = bpy.data.node_groups.new("QA_Copy", "ShaderNodeTree")
node = dest.nodes.new("ShaderNodeMath")
copy_fcurves(source, dest, node.inputs[0], "default_value")
curves = assigned_fcurves(dest)
assert len(curves) == 1
assert [(p.co.x, p.co.y) for p in curves[0].keyframe_points] == [(1, .25), (20, .75)]
# A real material action used to throw AttributeError in the paint reader.
mat = bpy.data.materials.new("QA_Scalar_Material")
mat.use_nodes = True
mat.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].keyframe_insert(
    "default_value", frame=1
)
assert len(get_material_fcurves(mat)) == 1
# Two node trees deliberately sharing an action but owning different slots.
other = tree.copy()
other.name = "QA_Foreign"
ad = other.animation_data_create()
ad.action = tree.animation_data.action
ad.action_slot = ad.action.slots.new(id_type="NODETREE", name="QA_Foreign")
other.mp.layers[0].keyframe_insert("intensity_value", frame=5)
assert len(assigned_fcurves(tree)) == len(assigned_fcurves(other)) == 1
result = True
'''

REMOVE_ANIMATION = '''
from mixar.modules.common.utils.animation import assigned_fcurves
from mixar.modules.paint.core.element.remove_fcurves import (
    remove_entity_fcurves, remove_channel_fcurves,
)
from mixar.modules.paint.utils.common_animation import get_action_and_driver_fcurves
tree = bpy.data.node_groups["QA_Paint"]
assert not tree.mp.layers[0].enable
remove_entity_fcurves(tree.mp.layers[0])
assert not assigned_fcurves(tree)
foreign = assigned_fcurves(bpy.data.node_groups["QA_Foreign"])
assert len(foreign) == 1 and len(foreign[0].keyframe_points) == 1
for channel in tree.mp.channels[:2]:
    channel.driver_add("enable_alpha")
collections = get_action_and_driver_fcurves(tree)
assert sum(c == tree.animation_data.drivers for c in collections) == 1
remove_channel_fcurves(tree.mp.channels[0])
assert len(tree.animation_data.drivers) == 1
assert ".channels[1]." in tree.animation_data.drivers[0].data_path
remove_channel_fcurves(tree.mp.channels[1])
assert not tree.animation_data.drivers
result = True
'''

OPEN_FILTERS = '''
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == "PROPERTIES")
s = a.spaces.active
for prop, label in (("show_properties_layers", "Layers"),
                    ("show_properties_strip", "Strip"),
                    ("show_properties_strip_modifier", "Strip Modifiers")):
    assert s.bl_rna.properties[prop].name == label
    setattr(s, prop, True)
r = next(r for r in a.regions if r.type == "WINDOW")
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.wm.call_panel(name="PROPERTIES_PT_visibility")
result = True
'''


def evaluate(qa, code):
    assert qa.eval(textwrap.dedent(code)) is True


def check_layer(qa, enabled):
    evaluate(qa, f'''
        from mixar.modules.common.utils.animation import assigned_fcurves
        tree = bpy.data.node_groups["QA_Paint"]
        assert tree.mp.layers[0].enable is {enabled}
        curves = assigned_fcurves(tree)
        assert len(curves) == 1
        curve = curves[0]
        assert [(p.co.x, p.co.y) for p in curve.keyframe_points] == [(1, .25), (20, .75)]
        assert curve.data_path.startswith({"nodes[" if enabled else "mp.layers["!r})
        tree.path_resolve(curve.data_path)
        result = True
    ''')


def run(qa):
    out = Path(os.environ.get("QA_SCENARIO_OUT", tempfile.mkdtemp(prefix="mixar-52-qa-")))
    out.mkdir(parents=True, exist_ok=True)
    evaluate(qa, 'import os; assert os.environ.get("MIXAR_QA") == "1"; result=True')
    # The QA socket starts before time-budgeted paint operator registration.
    qa.step("wait for paint registration", qa.wait,
            "'create_material' in dir(bpy.ops.layers)", timeout=60)
    qa.cmd("wait_login", timeout=90)
    qa.step("open Engine mode", qa.click, op="MIXAR_OT_set_ui_mode_pro")
    qa.wait("any(a.type == 'MIXIE' for a in drv.main_window().screen.areas)")
    qa.step("create animated paint fixture", evaluate, qa, SETUP)
    qa.wait("bool(drv.find(area_type='MIXAR_LAYERS', prop='enable'))")
    qa.step("disable animated layer", qa.click, area_type="MIXAR_LAYERS", prop="enable")
    qa.step("disabled keyframes remain valid", check_layer, qa, False)
    qa.step("enable animated layer", qa.click, area_type="MIXAR_LAYERS", prop="enable")
    qa.step("enabled keyframes remain valid", check_layer, qa, True)
    paint_snap = str(out / "animated-layer.png")
    qa.cmd("snap", path=paint_snap, area="MIXAR_LAYERS")
    qa.step("copy animation and isolate action slots", evaluate, qa, COPY_AND_SHARED_SLOT)
    qa.step("disable layer for removal", qa.click, area_type="MIXAR_LAYERS", prop="enable")
    qa.step("remove own curves and channel drivers", evaluate, qa, REMOVE_ANIMATION)
    qa.click(area_type="MIXAR_LAYERS", prop="enable")
    qa.step("open correct tab filters", evaluate, qa, OPEN_FILTERS)
    qa.step("toggle Strip visibility", qa.click, prop="show_properties_strip", popup=True)
    evaluate(qa, '''
        s = next(a.spaces.active for a in drv.main_window().screen.areas if a.type == "PROPERTIES")
        assert not s.show_properties_strip
        assert s.show_properties_layers and s.show_properties_strip_modifier
        result = True
    ''')
    qa.wait("all(not w.get('sel') for w in drv.find(prop='show_properties_strip', popup=True))")
    filter_snap = str(out / "tab-filter.png")
    qa.cmd("snap", path=filter_snap,
           target={"prop": "show_properties_strip", "popup": True}, margin=420)
    qa.press("ESC")
    return {"snapshots": [paint_snap, filter_snap], "credits_spent": 0}


if __name__ == "__main__":
    run_scenario("blender52_regressions", run)
