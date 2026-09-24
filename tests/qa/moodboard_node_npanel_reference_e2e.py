#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit: a selected generated node attaches as an N-panel reference.

Launch an isolated Dev app with the QA harness, then run:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/moodboard-node-npanel \
        python3 tests/qa/moodboard_node_npanel_reference_e2e.py
"""

import os
from pathlib import Path
import sys

from moodboard_drawer_e2e import (  # noqa: E402
    SCENE, SETUP, require, snap, switch_mode, target, toggle,
)

HARNESS = os.environ.get("QA_HARNESS")
if not HARNESS:
    raise SystemExit("Set QA_HARNESS to the local mixar-qa-harness checkout")
sys.path.insert(0, str(Path(HARNESS) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/moodboard-node-npanel"))


def fixture_node(qa):
    return qa.eval(SETUP + """
from mixar.modules.moodboard.core.node_graph import new_node_id
img = bpy.data.images.new('qa_node_result', 64, 64)
node = win.scene.mixie_moodboard_action_nodes.add()
node.node_id = new_node_id()
node.action_type = 'IMAGE_GEN'
node.state = 'SUCCESS'
node.selected = False
node.preview_image = img
item = win.scene.mixie_moodboard_images.add()
item.image = img
item.node_id = new_node_id()
item.embedded_node_id = node.node_id
item.selected = False
item.scale = 1.0
item.position_x, item.position_y = 40.0, 40.0
area.tag_redraw()
result = {'node_id': node.node_id, 'image': img.name}
""")


def references(qa):
    return qa.eval(f"""
from mixar.modules.moodboard.core.media_utils import (
    first_selected_reference_still, selected_reference_stills,
)
from mixar.modules.common.utils.mixie_space_utils import (
    count_selected_moodboard_images, get_first_selected_moodboard_image,
)
scene = {SCENE}
stills = selected_reference_stills(scene)
result = {{
    'count': count_selected_moodboard_images(scene),
    'names': [item.image.name for item in stills if item.image],
    'first': getattr(first_selected_reference_still(scene), 'name', None),
    'alias': getattr(get_first_selected_moodboard_image(scene), 'name', None),
    'direct': [i.image.name for i in scene.mixie_moodboard_images
               if i.selected and i.image],
}}
""")


def open_image_gen(qa):
    qa.eval(SETUP + """
space = area.spaces.active
space.show_region_ui = True
ui = next(r for r in area.regions if r.type == 'UI')
from mixar.modules.moodboard.ui.moodboard_sidebar_panels import get_tab_category
ui.active_panel_category = get_tab_category('image_gen', 'Image Gen')
win.scene.mixie_moodboard_sidebar.tab_imagegen.use_reference_images = True
area.tag_redraw()
result = True
""")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    switch_mode(qa, "mixar.set_zen_mode", "Zen Mode")
    toggle(qa, 1)
    created = fixture_node(qa)
    empty = references(qa)
    require(empty["count"] == 0 and empty["direct"] == [],
            f"Unselected node leaked into references: {empty}")

    qa.click(surface="moodboard_node", text=created["node_id"])
    qa.wait(f"any(n.node_id == {created['node_id']!r} and n.selected "
            f"for n in {SCENE}.mixie_moodboard_action_nodes)", timeout=4)
    attached = references(qa)
    require(attached["count"] == 1, f"Selected node did not count: {attached}")
    require(attached["names"] == [created["image"]],
            f"Wrong still attached: {attached}")
    require(attached["first"] == created["image"]
            and attached["alias"] == created["image"],
            f"First-still helpers diverged: {attached}")
    require(attached["direct"] == [],
            f"Node result was marked selected: {attached}")

    open_image_gen(qa)
    snap(qa, "01-image-gen-node-reference")
    return {"node_id": created["node_id"], "image": created["image"]}


if __name__ == "__main__":
    run_scenario(run)
