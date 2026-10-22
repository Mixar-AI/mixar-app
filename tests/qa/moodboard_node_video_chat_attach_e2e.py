#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit: a selected Video Gen node's clip attaches as a context-file chip.

A generated clip is an EMBEDDED board item whose own ``selected`` stays False;
a click selects the owning node. The chat-sync tick must still mirror it onto
a board-owned (``origin == "moodboard"``) context-file chip, never a still
pill, and drop that chip once the node is deselected.

Launch an isolated Dev app with the QA harness, then run:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/moodboard-node-video-chat \
        python3 tests/qa/moodboard_node_video_chat_attach_e2e.py
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from moodboard_drawer_e2e import (  # noqa: E402
    SCENE, SETUP, require, snap, switch_mode, toggle,
)

HARNESS = os.environ.get("QA_HARNESS")
if not HARNESS:
    raise SystemExit("Set QA_HARNESS to the local mixar-qa-harness checkout")
sys.path.insert(0, str(Path(HARNESS) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/moodboard-node-video-chat"))
CHECKS = Path(__file__).with_name("context_folder_video_checks.py").resolve()
CHIPS = f"[(i.name, i.origin) for i in {SCENE}.mixie_context_files]"


def fixture_node(qa):
    """A finished VIDEO_GEN node holding a local clip as its embedded result."""
    fixtures = OUT / "fixtures"
    return qa.eval(SETUP + f"""
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('vc', {str(CHECKS)!r})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fx = Path({str(fixtures)!r}); fx.mkdir(parents=True, exist_ok=True)
s = win.scene
from mixar.modules.context_folder.core import files
for fid in [i.file_id for i in s.mixie_context_files]: files.detach_file(s, fid)
clip = m.render_fixture(s, fx)
from mixar.modules.moodboard.core import chat_sync
from mixar.modules.moodboard.core.node_graph import (
    connect_video_result, deselect_graph_nodes, new_node_id,
)
chat_sync.register()
movie = bpy.data.images.load(str(clip), check_existing=False)
movie.source = 'MOVIE'
for it in s.mixie_moodboard_images: it.selected = False
deselect_graph_nodes(s)
node = s.mixie_moodboard_action_nodes.add()
node.node_id = new_node_id()
node.action_type = 'VIDEO_GEN'
node.state = 'SUCCESS'
node.position_x, node.position_y = 40.0, 40.0
item = s.mixie_moodboard_images.add()
item.image = movie
item.node_id = new_node_id()
item.scale = 1.0
item.position_x, item.position_y = 40.0, 40.0
connect_video_result(s, node, movie.name)
node.selected = False
area.tag_redraw()
result = {{'node_id': node.node_id, 'movie': movie.name,
          'embedded': item.embedded_node_id == node.node_id,
          'item_selected': bool(item.selected),
          'tick': bpy.app.timers.is_registered(chat_sync._poll_tick)}}
""")


def chat_state(qa):
    return qa.eval(f"""
s = {SCENE}
from mixar.modules.moodboard.core import chat_sync, chat_sync_videos
result = {{
    'chips': {CHIPS},
    'videos': list(chat_sync_videos.selected_video_names(s)),
    'pills': [a.image_path for a in s.mixie_chat_pending_attachments
              if getattr(a, 'is_moodboard', False)],
    'pill_names': chat_sync._collect_selected_image_names(s),
    'node_selected': [n.node_id for n in s.mixie_moodboard_action_nodes if n.selected],
    'item_selected': [i.image.name for i in s.mixie_moodboard_images
                      if i.selected and i.image],
}}
""")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    switch_mode(qa, "mixar.set_ui_mode_ai", "Zen Mode")
    toggle(qa, 1)
    created = fixture_node(qa)
    require(created["embedded"] and not created["item_selected"] and created["tick"],
            f"Fixture is not an embedded node result: {created}")
    idle = chat_state(qa)
    require(idle["chips"] == [] and idle["videos"] == [],
            f"Unselected node leaked a chip: {idle}")

    # A real click selects the NODE (embedded items are not hit-testable).
    qa.click(surface="moodboard_node", text=created["node_id"])
    qa.wait(f"any(n.node_id == {created['node_id']!r} and n.selected "
            f"for n in {SCENE}.mixie_moodboard_action_nodes)", timeout=4)
    qa.wait(f"any(o == 'moodboard' for _, o in {CHIPS})", timeout=6)
    attached = chat_state(qa)
    require(attached["chips"] == [["clip.mp4", "moodboard"]],
            f"Selected node clip did not attach: {attached}")
    require(attached["videos"] == [created["movie"]], f"Wrong video set: {attached}")
    require(attached["item_selected"] == [], f"Embedded item marked selected: {attached}")
    require(attached["pills"] == [] and attached["pill_names"] == [],
            f"Movie leaked into still pills: {attached}")
    snap(qa, "01-node-selected-chip")

    qa.eval(SETUP + "from mixar.modules.moodboard.core.node_graph import deselect_graph_nodes\n"
            "deselect_graph_nodes(win.scene)\narea.tag_redraw()\nresult = True")
    qa.wait(f"not {CHIPS}", timeout=6)
    detached = chat_state(qa)
    require(detached["chips"] == [] and detached["videos"] == [],
            f"Deselecting the node kept the chip: {detached}")
    snap(qa, "02-node-deselected-no-chip")
    return {"node_id": created["node_id"], "attached": attached, "detached": detached}


if __name__ == "__main__":
    run_scenario("moodboard_node_video_chat_attach", run)
