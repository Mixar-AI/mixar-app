#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit socket palette, zoom and precise connection GUI regression.

Run in a clean isolated Dev QA app with a live generation catalog:
    QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/moodboard_sockets_e2e.py
Use --before on the previous build to capture the old socket appearance.

Gallery cards are synthetic local fixtures for otherwise unavailable types;
they never claim to be generated results. File drops, continuation creation,
socket drags and zoom use actual input events. The catalog-backed Image Gen
card connects real image references. No generation is submitted. The gallery
is repositioned/resized after zoom so every type remains visible side by side;
the actual View2D zoom is asserted independently. Inspect the saved PNGs.
"""

import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QA_SCENARIO_OUT", str(Path(__file__).resolve().parents[2] /
                                            "build/qa/moodboard-sockets"))

from moodboard_drawer_e2e import (  # noqa: E402
    QA, OUT, SCENE, SETUP, drop, geometry, png, point, require, run_scenario,
    snap, switch_mode, target, toggle,
)
from moodboard_drawer_resize_links_e2e import canvas, resize  # noqa: E402
from moodboard_node_layout_e2e import assert_layout, node_code, place  # noqa: E402

CASES = (
    ("image", "Image / optional", "IMAGE", "IMAGE_GEN", False),
    ("video", "Video / optional", "VIDEO", "VIDEO_GEN", False),
    ("mesh", "Mesh / optional", "MESH", "MODEL_3D", False),
    ("mixed", "Image + video", "IMAGE,VIDEO", "IMAGE_GEN", False),
    ("unknown", "Unknown / neutral", "CUSTOM", "IMAGE_GEN", False),
    ("required", "Image / required", "IMAGE", "IMAGE_GEN", True),
    ("mixed_mesh", "Image + mesh", "IMAGE,MESH", "MODEL_3D", False),
)


def all_links(qa):
    return qa.eval(f"result=[(l.from_node_id,l.to_node_id,l.to_socket) "
                   f"for l in {SCENE}.mixie_moodboard_links]")


def clear_selection(qa):
    qa.eval(SETUP + """
for n in win.scene.mixie_moodboard_action_nodes:
    n.selected=False
for item in win.scene.mixie_moodboard_images:
    item.selected=False
win.scene.mixie_moodboard_active_node_id=''
area.tag_redraw()
""")


def place_media(qa, node_id, left, bottom, width=220):
    board = target(qa, "moodboard_drawer_panel")["rect"]
    qa.eval(SETUP + f"""
from mixar.modules.moodboard.constants import MOODBOARD_IMAGE_BASE_SIZE
item=next(i for i in win.scene.mixie_moodboard_images if i.node_id=={node_id!r})
x0,y0,x1,y1={board!r}
a=drawer.view2d.region_to_view(x0-drawer.x+{left},y0-drawer.y+{bottom})
b=drawer.view2d.region_to_view(x0-drawer.x+{left+width},y0-drawer.y+{bottom})
item.position_x,item.position_y=a
item.scale=(b[0]-a[0])/MOODBOARD_IMAGE_BASE_SIZE
area.tag_redraw()
""")


def fixture_gallery(qa):
    return qa.eval(SETUP + f"""
from mixar.modules.moodboard.core.node_graph import new_node_id
result={{}}
for key,label,accepted,action,required in {CASES!r}:
    node=win.scene.mixie_moodboard_action_nodes.add()
    node.node_id=new_node_id()
    node.action_type=action
    node.prompt=label
    node.state='DRAFT'
    node.selected=False
    socket=node.input_sockets.add()
    socket.socket_id='qa_input'
    socket.label=label
    socket.accepted_types=accepted
    socket.required=required
    socket.visible=True
    result[key]=node.node_id
area.tag_redraw()
""")


def arrange(qa, fixtures, references, action):
    # Keep physical card placement comparable at different canvas zooms.
    close = 1 / canvas(qa)["units_per_pixel"][0] > 2.5
    for index, case in enumerate(CASES):
        row, column = divmod(index, 4)
        place(qa, fixtures[case[0]], left=(100+column*600 if close else 160+column*550),
              bottom=(960-row*480 if close else 930-row*380), width=320, height=240)
    for index, reference in enumerate(references):
        place_media(qa, reference, 150+index*330, 100, width=210)
    place(qa, action, left=1950 if close else 1370, bottom=80, width=430, height=320)
    clear_selection(qa)


def continuation(qa, source):
    before = qa.eval(f"result=[n.node_id for n in {SCENE}.mixie_moodboard_action_nodes]")
    qa.click(surface="moodboard_output", text=source)
    qa.wait("bool(drv.find(popup=True,text='Generate Image'))", timeout=5)
    snap(qa, "01_output_continuation_popup")
    qa.click(popup=True, text="Generate Image")
    qa.wait(f"len({SCENE}.mixie_moodboard_action_nodes)=={len(before)+1}", timeout=5)
    nodes = qa.eval(f"result=[n.node_id for n in {SCENE}.mixie_moodboard_action_nodes]")
    action = next(n for n in nodes if n not in before)
    require(any(a == source and b == action for a, b, _ in all_links(qa)),
            "Output continuation did not wire its source")
    return action


def drag_to_next(qa, source, action):
    sockets = qa.find(surface="moodboard_socket", text=action, limit=50)["widgets"]
    occupied = {socket for _, node, socket in all_links(qa) if node == action}
    available = [w for w in sockets if w["detail"] not in occupied]
    require(available, "No empty catalog-backed reference socket")
    destination = max(available, key=lambda w: w["index"])
    before = all_links(qa)
    qa.cmd("drag", **{"from": {"surface": "moodboard_output", "text": source},
                      "to": {"surface": "moodboard_socket", "text": action,
                             "detail": destination["detail"]}, "steps": 18})
    qa.wait(f"any(l.from_node_id=={source!r} and l.to_node_id=={action!r} "
            f"and l.to_socket=={destination['detail']!r} "
            f"for l in {SCENE}.mixie_moodboard_links)", timeout=5)
    require(len(all_links(qa)) == len(before)+1,
            "Socket drag changed more than its requested connection")
    return {"source": source, "destination": destination, "links": all_links(qa)}


def zoom(qa, key, count):
    clear_selection(qa)
    board = target(qa, "moodboard_drawer_panel")
    xy = point(board, 0.94, 0.94)
    qa.eval(f"drv.move_to(drv.main_window(),{xy['x']},{xy['y']})")
    before = canvas(qa)["units_per_pixel"][0]
    for _ in range(count):
        qa.press(key)
    after = canvas(qa)["units_per_pixel"][0]
    require(after > before if key == "WHEELDOWNMOUSE" else after < before,
            f"Wheel did not change canvas zoom: {before} -> {after}")
    return {"units_per_pixel_before": before, "units_per_pixel_after": after}


def socket_targets(qa, fixtures, action):
    result = {}
    for key, _, _, _, _ in CASES:
        node_id = fixtures[key]
        result[key] = {
            "input": target(qa, "moodboard_socket", text=node_id, detail="qa_input"),
            "output": target(qa, "moodboard_output", text=node_id),
        }
    result["connected_inputs"] = qa.find(
        surface="moodboard_socket", text=action, limit=50)["widgets"]
    return result


def sample_visuals(qa, fixtures, action, name):
    """Measure rendered single-socket extents against their native QA targets.

    Pixel inspection uses the captured app image, not a recreated diagram.
    Crowded real input rows can tighten below the nominal visual-size floor;
    their exact connection is checked separately with real drag events.
    """
    from PIL import Image

    targets = socket_targets(qa, fixtures, action)
    path = OUT / f"{name}.png"
    capture = qa.cmd("snap", path=str(path))
    image = Image.open(path).convert("RGB")
    width, height = image.size
    scale = qa.eval("result=bpy.context.preferences.system.ui_scale")
    measurements = {}

    def center_rgb(widget):
        x, y = (round(v) for v in widget["center"])
        return image.getpixel((x, height-1-y))

    require(max(center_rgb(targets["image"]["input"])) < 90,
            "Optional empty input should retain a dark center")
    require(min(center_rgb(targets["image"]["output"])) > 150,
            "Output handle lacks a clear neutral plus at its center")
    occupied = {s for _, node, s in all_links(qa) if node == action}
    for widget in targets["connected_inputs"]:
        rgb = center_rgb(widget)
        if widget["detail"] in occupied:
            require(rgb[1] > rgb[0]*1.15 and rgb[2] > rgb[0]*1.15 and max(rgb) > 90,
                    f"Connected image input lacks a colored center pip: {widget}")
        else:
            require(max(rgb) < 90, "Empty input center looks connected")
    for key in ("image", "video", "mesh"):
        measurements[key] = {}
        for direction in ("input", "output"):
            widget = targets[key][direction]
            x, y = (round(v) for v in widget["center"])
            py = height-1-y
            require(0 <= x < width and 0 <= py < height,
                    f"Socket center outside screenshot: {widget}")

            def colored(rgb):
                r, g, b = rgb
                if key == "image":
                    return g > r*1.18 and b > r*1.18 and max(rgb) > 90
                if key == "video":
                    return r > g*1.12 and b > g*1.18 and max(rgb) > 90
                return g > r*1.20 and g > b*1.08 and max(rgb) > 90

            span = round(14*scale)
            pixels = [(xx, yy) for yy in range(max(0, py-2), min(height, py+3))
                      for xx in range(max(0, x-span), min(width, x+span+1))
                      if colored(image.getpixel((xx, yy)))]
            require(pixels, f"No expected {key} rim pixels for {direction}")
            radius = max(abs(xx-x) for xx, _ in pixels)
            low, high = (6, 8) if direction == "input" else (8, 10)
            require(low*scale-3 <= radius <= high*scale+3,
                    f"{key} {direction} radius {radius}px escapes {low}..{high} UI bounds")
            if 1 / canvas(qa)["units_per_pixel"][0] > 2.5:
                require(abs(radius-high*scale) <= 3,
                        f"Close zoom does not exercise {direction} upper size clamp")
            hit_radius = (widget["rect"][2]-widget["rect"][0])/2
            require(hit_radius >= 12*scale-1 and hit_radius > radius,
                    f"Native target does not contain the visible socket: {widget}")
            measurements[key][direction] = {"radius_px": radius,
                                            "hit_radius_px": hit_radius}
    return {"capture": capture, "targets": targets, "measurements": measurements,
            "units_per_pixel": canvas(qa)["units_per_pixel"]}


def selected_labels(qa, fixtures, references, action):
    # Isolate the real card so its native labels and dock clearance are reviewable.
    zoom(qa, "WHEELDOWNMOUSE", 14)
    for node_id in fixtures.values():
        place(qa, node_id, left=-10000, bottom=100)
    for index, reference in enumerate(references):
        place_media(qa, reference, 150+index*330, 100, width=210)
    place(qa, action, left=1350, bottom=480, width=560, height=460)
    clear_selection(qa)
    qa.click(surface="moodboard_node", text=action)
    qa.wait(f"any(n.node_id=={action!r} and n.selected "
            f"for n in {SCENE}.mixie_moodboard_action_nodes)", timeout=5)
    layout = assert_layout(qa, action, compact=False)
    return {"layout": layout, "capture": snap(qa, "05_selected_socket_labels"),
            "sockets": qa.find(surface="moodboard_socket", text=action, limit=50)}


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            "Use an isolated QA app")
    qa.step("idle", qa.wait, f"{SCENE}.mixie_chat_state=='IDLE'", timeout=45)
    require(qa.eval(f"result=not {SCENE}.mixie_moodboard_action_nodes and "
                    f"not {SCENE}.mixie_moodboard_images"), "Use a clean QA scene")
    if geometry(qa)["workspace"] != "Zen Mode":
        switch_mode(qa, "mixar.set_ui_mode_ai", "Zen Mode")
    qa.step("catalog", qa.wait,
            "__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)
    if geometry(qa)["amount"] < 0.98:
        toggle(qa, 1)
    qa.step("wide_canvas", resize, qa, min(2600, geometry(qa)["area"][2]-60))
    red = png(OUT / "reference-red.png", (150, 65, 60))
    first = qa.step("reference_drop", drop, qa, red,
                    **point(target(qa, "moodboard_drawer_panel"), 0.2, 0.25))
    place_media(qa, first, 150, 100)
    action = qa.step("real_output_continuation", continuation, qa, first)
    place(qa, action, left=1370, bottom=80, width=430, height=320)
    blue = png(OUT / "reference-blue.png", (60, 95, 155))
    second = qa.step("second_reference", drop, qa, blue,
                     **point(target(qa, "moodboard_drawer_panel"), 0.25, 0.25))
    place_media(qa, second, 480, 100)
    clear_selection(qa)
    second_link = qa.step("exact_second_input_drag", drag_to_next, qa, second, action)
    fixtures = qa.step("synthetic_type_gallery", fixture_gallery, qa)
    references = [first, second]
    qa.step("arrange_gallery", arrange, qa, fixtures, references, action)
    if "--before" in sys.argv:
        snap(qa, "00_before_sockets")
        return {"before_only": True, "credits_spent": 0, "fixtures": fixtures,
                "real_action": action, "links": all_links(qa)}

    evidence = {"second_input": second_link}
    evidence["normal"] = qa.step("normal_pixels_and_targets", sample_visuals,
                                  qa, fixtures, action, "02_normal_socket_palette")
    evidence["overview_zoom"] = qa.step("zoom_overview", zoom, qa, "WHEELDOWNMOUSE", 5)
    arrange(qa, fixtures, references, action)
    green = png(OUT / "reference-green.png", (65, 120, 85))
    third = drop(qa, green, **point(target(qa, "moodboard_drawer_panel"), 0.35, 0.25))
    references.append(third)
    arrange(qa, fixtures, references, action)
    evidence["crowded_input"] = qa.step("overview_exact_empty_input", drag_to_next,
                                        qa, third, action)
    evidence["overview"] = qa.step("overview_pixels_and_targets", sample_visuals,
                                    qa, fixtures, action, "03_overview_socket_palette")
    evidence["close_zoom"] = qa.step("zoom_close", zoom, qa, "WHEELUPMOUSE", 24)
    require(1 / canvas(qa)["units_per_pixel"][0] > 2.5,
            "Close canvas zoom must exceed 2.5 to exercise upper socket size clamps")
    arrange(qa, fixtures, references, action)
    evidence["close"] = qa.step("close_pixels_and_targets", sample_visuals,
                                 qa, fixtures, action, "04_close_socket_palette")
    evidence["selected_labels"] = qa.step("selected_labels_and_dock", selected_labels,
                                           qa, fixtures, references, action)
    require(qa.eval(f"result=all(n.state=='DRAFT' and not n.job_id "
                    f"for n in {SCENE}.mixie_moodboard_action_nodes)"),
            "A fixture unexpectedly submitted work")
    result = {"credits_spent": 0, "synthetic_gallery": True,
              "real_reference_connections": 3, "screenshots": str(OUT),
              "evidence": evidence}
    (OUT / "state-evidence.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run_scenario("moodboard_sockets_e2e", run)
