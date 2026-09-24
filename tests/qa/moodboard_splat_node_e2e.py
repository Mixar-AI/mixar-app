#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit: Generate Splat continues from a still or an Image Gen node.

Launch an isolated Dev app with the QA harness, then run:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/moodboard-splat-node \
        python3 tests/qa/moodboard_splat_node_e2e.py
"""

import os
from pathlib import Path
import sys

from moodboard_drawer_e2e import (  # noqa: E402
    SCENE, SETUP, require, snap, switch_mode, toggle,
)

HARNESS = os.environ.get("QA_HARNESS")
if not HARNESS:
    raise SystemExit("Set QA_HARNESS to the local mixar-qa-harness checkout")
sys.path.insert(0, str(Path(HARNESS) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/moodboard-splat-node"))


def fixture_graph(qa):
    return qa.eval(SETUP + """
from mixar.modules.moodboard.core.node_graph import (
    create_connected_action, new_node_id, node_output_type,
)
from mixar.modules.moodboard.core.node_schema import output_type_for_action

img = bpy.data.images.new('qa_splat_still', 64, 64)
still = win.scene.mixie_moodboard_images.add()
still.image = img
still.node_id = new_node_id()
still.selected = True
still.scale = 1.0
still.position_x, still.position_y = 40.0, 40.0

igen = win.scene.mixie_moodboard_action_nodes.add()
igen.node_id = new_node_id()
igen.action_type = 'IMAGE_GEN'
igen.state = 'SUCCESS'
igen.selected = False
igen.preview_image = img
igen.position_x, igen.position_y = 280.0, 40.0
embedded = win.scene.mixie_moodboard_images.add()
embedded.image = img
embedded.node_id = new_node_id()
embedded.embedded_node_id = igen.node_id
embedded.selected = False

from_still = create_connected_action(win.scene, 'WORLD_LABS', still.node_id)
from_gen = create_connected_action(win.scene, 'WORLD_LABS', igen.node_id)
area.tag_redraw()
result = {
    'still_id': still.node_id,
    'image_gen_id': igen.node_id,
    'from_still': from_still.node_id,
    'from_gen': from_gen.node_id,
    'from_still_type': from_still.action_type,
    'from_gen_type': from_gen.action_type,
    'still_output': node_output_type(win.scene, still.node_id),
    'gen_output': node_output_type(win.scene, igen.node_id),
    'splat_output': output_type_for_action('WORLD_LABS'),
    'from_still_out': node_output_type(win.scene, from_still.node_id),
    'from_gen_out': node_output_type(win.scene, from_gen.node_id),
    'from_still_sockets': [s.accepted_types for s in from_still.input_sockets],
    'from_gen_sockets': [s.accepted_types for s in from_gen.input_sockets],
    'links': [
        (link.from_node_id, link.to_node_id)
        for link in win.scene.mixie_moodboard_links
    ],
}
""")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    switch_mode(qa, "mixar.set_zen_mode", "Zen Mode")
    toggle(qa, 1)
    state = fixture_graph(qa)
    require(state["from_still_type"] == "WORLD_LABS", state)
    require(state["from_gen_type"] == "WORLD_LABS", state)
    require(state["still_output"] == "IMAGE", state)
    require(state["gen_output"] == "IMAGE", state)
    require(state["splat_output"] == "SPLAT", state)
    require(state["from_still_out"] == "SPLAT", state)
    require(state["from_gen_out"] == "SPLAT", state)
    require(
        any("IMAGE" in types for types in state["from_still_sockets"]),
        f"Splat node from still missing IMAGE socket: {state}",
    )
    require(
        any("IMAGE" in types for types in state["from_gen_sockets"]),
        f"Splat node from Image Gen missing IMAGE socket: {state}",
    )
    require(
        (state["still_id"], state["from_still"]) in state["links"],
        f"Still was not wired into splat: {state}",
    )
    require(
        (state["image_gen_id"], state["from_gen"]) in state["links"],
        f"Image Gen was not wired into splat: {state}",
    )
    snap(qa, "01-splat-nodes")
    return {"backend_submissions": 0, "screenshots": str(OUT), "state": state}


if __name__ == "__main__":
    run_scenario("moodboard_splat_node_e2e", run)
