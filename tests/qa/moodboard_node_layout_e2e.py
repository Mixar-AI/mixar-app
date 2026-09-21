#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit moodboard node controls: layout, settings, selection and busy state.

Run against an isolated, logged-in Dev QA app with its live catalog:
    QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/moodboard_node_layout_e2e.py

Optional --before captures the old overlapping layout without new assertions.
Fixture creation/placement and synthetic running state use eval; resize, popup,
parameter editing, reset, selection, pan and cancel use real input events.
Generate is NEVER clicked. Read the saved PNGs as well as the state verdict.
"""

import json
import os
from pathlib import Path
import sys

os.environ.setdefault(
    "QA_SCENARIO_OUT", str(Path(__file__).resolve().parents[2] /
                           "build/qa/moodboard-node-layout"))

from moodboard_drawer_e2e import (  # noqa: E402
    QA, OUT, SCENE, SETUP, geometry, point, require, run_scenario, snap,
    switch_mode, target, toggle,
)
from moodboard_drawer_resize_links_e2e import canvas, pan, resize  # noqa: E402

SETTINGS = "MIXIE_OT_moodboard_node_settings"
RESET = "MIXIE_OT_moodboard_reset_node_params"
GENERATE = "MIXIE_OT_moodboard_run_action_node"
CANCEL = "MIXIE_OT_moodboard_cancel_action_node"
BLOCK = "moodboard_floating_node_controls"
REGION = {"area_type": "VIEW_3D", "region_type": "TOOL_PROPS"}


def node_code(node_id):
    return SETUP + (
        f"node=next(n for n in win.scene.mixie_moodboard_action_nodes "
        f"if n.node_id == {node_id!r})\n")


def widgets(qa, popup=False):
    if popup:
        return qa.find(popup=True, limit=500)["widgets"]
    return [w for w in qa.find(**REGION, limit=500)["widgets"]
            if w.get("block") == BLOCK]


def one(items, key, value):
    hits = [w for w in items if w.get(key) == value]
    require(len(hits) == 1, f"Expected one {key}={value}, found {hits}")
    return hits[0]


def inside(inner, outer, tolerance=1):
    return (inner[0] >= outer[0]-tolerance and inner[1] >= outer[1]-tolerance
            and inner[2] <= outer[2]+tolerance and inner[3] <= outer[3]+tolerance)


def overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0])+1 and \
        min(a[3], b[3]) > max(a[1], b[1])+1


def assert_layout(qa, node_id, compact=None, busy=False):
    board = target(qa, "moodboard_drawer_panel")["rect"]
    card = target(qa, "moodboard_node", text=node_id)["rect"]
    controls = widgets(qa)
    require(controls, "Selected visible node has no controls")
    for control in controls:
        require(inside(control["rect"], board),
                f"Control escapes painted drawer: {control}")
    inputs = [w for w in controls if w.get("prop") or w.get("op")]
    for i, first in enumerate(inputs):
        for second in inputs[i+1:]:
            require(not overlaps(first["rect"], second["rect"]),
                    f"Interactive controls overlap: {first} / {second}")
    action = one(controls, "op", CANCEL if busy else GENERATE)
    require(inside(action["rect"], card), "Primary action escapes visible node")
    prompt = [w for w in controls if w.get("prop") == "prompt"]
    require(len(prompt) == (0 if busy else 1), "Prompt ownership/state mismatch")
    if prompt:
        require(inside(prompt[0]["rect"], card), "Prompt escapes visible node")
    settings = [w for w in controls if w.get("op") == SETTINGS]
    if compact is not None:
        require(bool(settings) == compact, f"Unexpected settings layout: {controls}")
    if settings:
        require(inside(settings[0]["rect"], card), "Compact Settings escapes node")
    for control in controls:
        if control.get("op") in {SETTINGS, RESET, CANCEL}:
            require(control.get("mixar_theme") == "ZEN" and
                    control.get("mixar_variant") != "PRIMARY",
                    f"Secondary action has primary styling: {control}")
    return {"board": board, "card": card, "controls": controls}


def place(qa, node_id, left=220, bottom=None, width=430, height=360):
    """Place fixture in canvas units derived from the live drawer transform."""
    board = target(qa, "moodboard_drawer_panel")["rect"]
    return qa.eval(node_code(node_id) + f"""
x0,y0,x1,y1={board!r}
x=x0-drawer.x+{left!r}
y=((y0+y1)/2-drawer.y-{height}/2 if {bottom!r} is None
   else y0-drawer.y+({bottom!r} or 0))
a=drawer.view2d.region_to_view(x,y)
b=drawer.view2d.region_to_view(x+{width},y+{height})
node.position_x,node.position_y=a
node.width=b[0]-a[0]
node.height=b[1]-a[1]
area.tag_redraw()
result={{'position':list(a),'size':[node.width,node.height]}}
""")


def new_node(qa):
    return qa.eval(SETUP + """
from mixar.modules.moodboard.core.node_graph import create_connected_action
node=create_connected_action(win.scene,'IMAGE_GEN')
area.tag_redraw()
result=node.node_id
""")


def parameters(qa, node_id):
    return qa.eval(node_code(node_id) + """
result=[{'name':p.name,'label':p.label,'type':p.parameter_type,
         'minimum':p.minimum,'maximum':p.maximum,
         'value':p.value_integer if p.parameter_type=='INTEGER' else p.value_float}
        for p in node.parameters if p.visible]
""")


def popup(qa):
    qa.click(op=SETTINGS, **REGION)
    qa.wait("bool(drv.find(popup=True, op='" + RESET + "'))", timeout=5)
    return widgets(qa, popup=True)


def dismiss_popup(qa):
    qa.press("ESC")
    qa.wait("not drv.find(popup=True)", timeout=5)


def settings_edit_reset(qa, node_id):
    fields = parameters(qa, node_id)
    synthetic = not any(p['type'] == 'INTEGER' and p['maximum'] > p['minimum']
                        for p in fields)
    if synthetic:
        # The live catalog may expose only enums. A local schema fixture pins
        # numeric bounds without changing the catalog or choosing a provider.
        qa.eval(node_code(node_id) + """
p=node.parameters.add()
p.name='qa_bounded_integer'
p.label='QA bounded count'
p.parameter_type='INTEGER'
p.visible=True
p.minimum=1
p.maximum=4
p.value_integer=1
area.tag_redraw()
""")
    try:
        result = _settings_edit_reset(qa, node_id)
        result['synthetic_numeric_schema'] = synthetic
        return result
    finally:
        if synthetic:
            qa.eval(node_code(node_id) + """
for i in reversed(range(len(node.parameters))):
    if node.parameters[i].name=='qa_bounded_integer':
        node.parameters.remove(i)
area.tag_redraw()
""")


def _settings_edit_reset(qa, node_id):
    fields = parameters(qa, node_id)
    items = popup(qa)
    labels = {w.get("text", "") for w in items}
    require("Model" in labels, "Settings popup hides the model caption")
    for parameter in fields:
        require(parameter["label"] in labels,
                f"Catalog caption missing: {parameter['label']}")
    candidates = [p for p in fields if p["type"] == "INTEGER" and
                  p["maximum"] > p["minimum"]]
    require(candidates, "Live image catalog has no editable bounded integer")
    parameter = candidates[0]
    integer_items = [w for w in items if w.get("prop") == "value_integer"]
    require(len(integer_items) == 1,
            "Fixture needs one unambiguous integer field for semantic editing")
    changed = parameter["value"]+1
    if changed > parameter["maximum"]:
        changed = parameter["value"]-1
    qa.cmd("set_text", widget={"popup": True, "prop": "value_integer"},
           text=str(changed))
    qa.wait(f"any(p.name=={parameter['name']!r} and p.value_integer=={changed} "
            f"for n in {SCENE}.mixie_moodboard_action_nodes if n.node_id=={node_id!r} "
            "for p in n.parameters)", timeout=4)
    qa.cmd("set_text", widget={"popup": True, "prop": "value_integer"},
           text=str(int(parameter["maximum"])+100))
    qa.wait(f"any(p.name=={parameter['name']!r} and p.value_integer=={parameter['maximum']} "
            f"for n in {SCENE}.mixie_moodboard_action_nodes if n.node_id=={node_id!r} "
            "for p in n.parameters)", timeout=4)
    snap(qa, "02_settings_popup_edited")
    if not qa.find(popup=True, op=RESET)["total"]:
        popup(qa)
    reset = one(widgets(qa, popup=True), "op", RESET)
    require(reset["mixar_theme"] == "ZEN" and reset["mixar_variant"] != "PRIMARY",
            "Popup reset competes with Generate")
    qa.click(popup=True, op=RESET)
    qa.wait(f"any(p.name=={parameter['name']!r} and p.value_integer=={parameter['value']} "
            f"for n in {SCENE}.mixie_moodboard_action_nodes if n.node_id=={node_id!r} "
            "for p in n.parameters)", timeout=4)
    if qa.find(popup=True)["total"]:
        dismiss_popup(qa)
    return {"parameter": parameter["name"], "edited": changed,
            "upper_bound": parameter["maximum"], "reset": parameter["value"]}


def busy_state(qa, node_id):
    qa.eval(node_code(node_id) + "node.state='RUNNING'\narea.tag_redraw()")
    try:
        state = assert_layout(qa, node_id, compact=True, busy=True)
        items = popup(qa)
        locked = [w for w in items if w.get("prop") in
                  {"model", "service_key", "value_enum", "value_integer", "value_float"}]
        require(locked and all(not w["enabled"] for w in locked),
                "Running settings remain editable")
        require(not one(items, "op", RESET)["enabled"], "Running Reset remains enabled")
        snap(qa, "07_running_settings_popup")
        dismiss_popup(qa)
        qa.click(op=CANCEL, **REGION)
        qa.wait(f"any(n.node_id=={node_id!r} and n.state=='CANCELLED' "
                f"for n in {SCENE}.mixie_moodboard_action_nodes)", timeout=4)
        return state
    finally:
        qa.eval(node_code(node_id) + "node.state='DRAFT'\narea.tag_redraw()")


def default_tall_terminal(qa, node_id):
    scale = qa.eval("result=bpy.context.preferences.system.ui_scale")
    if abs(canvas(qa)["width"] - 340 * scale) > 3:
        resize(qa, round(340 * scale))
    place(qa, node_id, left=80)
    default = assert_layout(qa, node_id, compact=True)
    snap(qa, "09_default_width")
    # Temporarily extend this isolated node's local schema to force native
    # popup scrolling. These fields are removed without changing the catalog.
    qa.eval(node_code(node_id) + """
for i in range(28):
    parameter=node.parameters.add()
    parameter.name=f'qa_layout_{i}'
    parameter.label=f'QA field {i+1:02d}'
    parameter.parameter_type='STRING'
    parameter.visible=True
area.tag_redraw()
""")
    try:
        qa.click(op=SETTINGS, **REGION)
        qa.wait("bool(drv.find(popup=True, prop='model'))", timeout=4)
        first = widgets(qa, popup=True)
        require(any(w.get("text") == "QA field 01" for w in first),
                "Tall popup does not start with its first fields")
        require(not any(w.get("text") == "QA field 28" for w in first),
                "Tall fixture did not exercise scrolling")
        snap(qa, "10_tall_settings_popup_top")
        anchor = next(w for w in first if w.get("prop"))
        xy = point(anchor)
        qa.eval(f"drv.move_to(drv.main_window(),{xy['x']},{xy['y']})")
        for _ in range(30):
            qa.press("WHEELDOWNMOUSE")
        last = widgets(qa, popup=True)
        require(any(w.get("text") == "QA field 28" for w in last),
                "Native popup scrolling cannot reach the final field")
        require(one(last, "op", RESET)["enabled"], "Scrolled Reset is unreachable")
        snap(qa, "11_tall_settings_popup_bottom")
        dismiss_popup(qa)
    finally:
        qa.eval(node_code(node_id) + """
for i in reversed(range(len(node.parameters))):
    if node.parameters[i].name.startswith('qa_layout_'):
        node.parameters.remove(i)
area.tag_redraw()
""")

    qa.eval(node_code(node_id) + """
image=bpy.data.images.new('QA_NODE_LAYOUT_RESULT',width=32,height=32)
image.generated_color=(0.12,0.38,0.52,1.0)
node.preview_image=image
node.state='SUCCESS'
area.tag_redraw()
""")
    try:
        require(not qa.find(op=GENERATE, **REGION)["total"],
                "Completed result still presents Generate over its preview")
        qa.click(op='MIXIE_OT_moodboard_toggle_node_edit', **REGION)
        items = popup(qa)
        edit = one(items, "op", GENERATE)
        require(edit["text"] == "Edit & Run Again", "Result lacks edit entry point")
        snap(qa, "12_completed_settings_popup")
        qa.click(popup=True, op=GENERATE)
        qa.wait(f"any(n.node_id=={node_id!r} and n.state=='DRAFT' "
                f"for n in {SCENE}.mixie_moodboard_action_nodes)", timeout=4)
        if qa.find(popup=True)["total"]:
            dismiss_popup(qa)
        assert_layout(qa, node_id, compact=True)
        snap(qa, "13_edit_without_submission")
    finally:
        qa.eval(node_code(node_id) + """
image=node.preview_image
node.preview_image=None
node.state='DRAFT'
if image and image.name.startswith('QA_NODE_LAYOUT_RESULT'):
    bpy.data.images.remove(image)
area.tag_redraw()
""")
    qa.eval(node_code(node_id) + """
node.preview_object=next(o for o in win.scene.objects if o.type=='MESH')
preview=node.preview_object.preview_ensure()
preview.image_size=(64,64)
preview.image_pixels_float=[0.12,0.38,0.52,1.0]*(64*64)
preview.icon_size=(32,32)
preview.icon_pixels_float=[0.12,0.38,0.52,1.0]*(32*32)
node.state='SUCCESS'
area.tag_redraw()
""")
    try:
        if not qa.find(op=SETTINGS, **REGION)['total']:
            qa.click(op='MIXIE_OT_moodboard_toggle_node_edit', **REGION)
        require(qa.find(op=SETTINGS, **REGION)["total"] == 1,
                "Editing an object result lost Settings")
        snap(qa, "14_compact_object_result")
        items = popup(qa)
        require(one(items, "op", GENERATE)["text"] == "Edit & Run Again",
                "Object result lacks edit entry point")
        qa.click(popup=True, op=GENERATE)
        qa.wait(f"any(n.node_id=={node_id!r} and n.state=='DRAFT' "
                f"for n in {SCENE}.mixie_moodboard_action_nodes)", timeout=4)
        if qa.find(popup=True)["total"]:
            dismiss_popup(qa)
        assert_layout(qa, node_id, compact=True)
        snap(qa, "15_object_edit_prompt")
    finally:
        qa.eval(node_code(node_id) +
                "node.preview_object=None\nnode.state='DRAFT'\narea.tag_redraw()")
    return {"default_width": default, "tall_popup_final_field": 28,
            "terminal_edit_returns_draft": True, "object_preview_controls": True}


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA') == '1'"),
            "Use an isolated QA app")
    qa.step("idle", qa.wait, f"{SCENE}.mixie_chat_state=='IDLE'", timeout=45)
    require(qa.eval(f"result=not {SCENE}.mixie_moodboard_action_nodes"),
            "Use a clean QA scene: reset-state before replay")
    if geometry(qa)["workspace"] != "Zen Mode":
        qa.step("enter_zen", switch_mode, qa, "mixar.set_ui_mode_ai", "Zen Mode")
    qa.step("catalog", qa.wait,
            "__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)
    if geometry(qa)["amount"] < 0.98:
        qa.step("open_drawer", toggle, qa, 1)
    qa.step("narrow_drawer", resize, qa, 1000)
    node_id = qa.step("draft_fixture", new_node, qa)
    qa.step("place_near_left", place, qa, node_id)
    qa.wait("bool(drv.find(prop='prompt',region_type='TOOL_PROPS'))", timeout=5)
    if "--before" in sys.argv:
        snap(qa, "00_before_narrow_overlap")
        return {"before_only": True, "node": node_id, "credits_spent": 0}
    evidence = {"narrow": qa.step("compact_inside_drawer", assert_layout, qa, node_id, True)}
    qa.step("snap_compact", snap, qa, "01_compact_narrow")
    evidence["settings"] = qa.step("edit_reset", settings_edit_reset, qa, node_id)

    wide = min(2300, geometry(qa)["area"][2]-80)
    qa.step("expand_drawer", resize, qa, wide)
    # Settings keep one stable entry point at every width and card position.
    qa.step("place_right", place, qa, node_id, 900)
    qa.step("right_card_settings", assert_layout, qa, node_id, True)
    qa.step("snap_right_card", snap, qa, "03_right_card")
    qa.step("place_left", place, qa, node_id, 120)
    qa.step("left_card_settings", assert_layout, qa, node_id, True)
    qa.step("snap_left_card", snap, qa, "04_left_card")
    qa.step("pan_to_left_boundary", pan, qa, -110)
    evidence["boundary"] = qa.step("boundary_inside_drawer", assert_layout, qa, node_id)
    qa.step("snap_boundary", snap, qa, "05_boundary_pan")

    # Two ordinary cards plus a Shift-click (zero-distance drag) exercise the
    # active inspector owner without mutating selection flags as a substitute.
    qa.step("restore_first_position", place, qa, node_id, 900)
    second = qa.step("second_draft", new_node, qa)
    qa.step("second_position", place, qa, second, 1350)
    # The second card's inspector can cover the first card's center. Deselect
    # on known empty canvas before testing the semantic card click.
    qa.cmd("click_xy", **point(target(qa, "moodboard_drawer_panel"), 0.94, 0.94))
    qa.click(surface="moodboard_node", text=node_id)
    qa.cmd("drag", **{"from": {"surface": "moodboard_node", "text": second},
                      "to": {"surface": "moodboard_node", "text": second},
                      "shift": True, "steps": 2})
    qa.wait(f"sum(n.selected for n in {SCENE}.mixie_moodboard_action_nodes)==2",
            timeout=4)
    require(qa.eval(f"result={SCENE}.mixie_moodboard_active_node_id") == second,
            "Shift-click did not transfer active inspector ownership")
    evidence["multi_selection"] = assert_layout(qa, second)
    snap(qa, "06_single_active_inspector")

    qa.step("return_narrow", resize, qa, 1000)
    qa.step("place_busy_fixture", place, qa, second)
    qa.step("busy_state_and_cancel", busy_state, qa, second)
    qa.step("recovered_draft", assert_layout, qa, second, True)
    qa.step("snap_recovered", snap, qa, "08_recovered_draft")
    evidence["additional"] = qa.step("default_tall_terminal", default_tall_terminal,
                                    qa, second)
    result = {"credits_spent": 0, "synthetic_busy_state": True,
              "screenshots": str(OUT), "evidence": evidence}
    (OUT / "state-evidence.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run_scenario("moodboard_node_layout_e2e", run)
