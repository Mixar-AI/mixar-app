#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit GUI regression for the Zen moodboard drawer.

Launch an isolated Dev app with the QA harness, then run:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/moodboard-drawer python3 tests/qa/moodboard_drawer_e2e.py

All feature actions use real simulated mouse/key/file-drop events. Eval reads
state or switches the initial workspace. Screenshots must also be viewed by
the QA agent; a green verdict alone cannot establish visual correctness.
"""

import os
from pathlib import Path
import struct
import shutil
import subprocess
import sys
import time
import zlib

HARNESS = os.environ.get("QA_HARNESS")
if not HARNESS:
    raise SystemExit("Set QA_HARNESS to the local mixar-qa-harness checkout")
sys.path.insert(0, str(Path(HARNESS) / "scenarios"))
from lib import QA, ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/moodboard-drawer"))
SCENE = "drv.main_window().scene"
AMOUNT = "bpy.context.window_manager.mixar_moodboard_drawer_amount"
SETUP = """
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
viewport = next(r for r in area.regions if r.type == 'WINDOW')
drawer = next((r for r in area.regions if r.type == 'TOOL_PROPS'), None)
"""
GEOMETRY = SETUP + """
rv3d = area.spaces.active.region_3d
rect = lambda r: [r.x, r.y, r.x + r.width, r.y + r.height]
result = {
    'workspace': win.workspace.name,
    'amount': getattr(bpy.context.window_manager, 'mixar_moodboard_drawer_amount', None),
    'viewport': rect(viewport),
    'area': rect(area),
    'drawer': rect(drawer) if drawer and drawer.width > 1 else None,
    'view': [list(rv3d.view_rotation), list(rv3d.view_location), rv3d.view_distance],
    'objects': sorted(o.name for o in bpy.data.objects),
}
"""


def require(condition, message):
    if not condition:
        raise ScenarioFail(message)


def geometry(qa):
    return qa.eval(GEOMETRY)


def target(qa, surface, **query):
    widgets = qa.find(surface=surface, **query)["widgets"]
    require(len(widgets) == 1, f"Expected one {surface} {query}, got {widgets}")
    return widgets[0]


def point(widget, fx=0.5, fy=0.5):
    x0, y0, x1, y1 = widget["rect"]
    return {"x": round(x0 + fx * (x1 - x0)), "y": round(y0 + fy * (y1 - y0))}


def settle(qa, amount):
    qa.wait(f"abs({AMOUNT} - {amount}) < 0.002", timeout=8)


def toggle(qa, amount):
    qa.click(surface="moodboard_drawer_grip")
    settle(qa, amount)


def drag_grip(qa, direction, amount, travel=0.85):
    grip = target(qa, "moodboard_drawer_grip")
    panel_width = geometry(qa)["drawer"]
    width = panel_width[2] - panel_width[0]
    start = point(grip)
    qa.cmd("drag", **{"from": {"surface": "moodboard_drawer_grip"},
                      "to": {"x": start["x"] + direction * round(width * travel),
                             "y": start["y"]}, "steps": 14})
    settle(qa, amount)


def snap(qa, name, annotate=False):
    args = {"path": str(OUT / f"{name}.png")}
    if "popup" not in name and "context_menu" not in name and name != "invalid_drop":
        args["area"] = "VIEW_3D"
    if annotate:
        args["annotate"] = {"area_type": "VIEW_3D", "but_type": "Custom"}
    return qa.cmd("snap", **args)


def media(qa):
    return qa.eval(
        f"result = [{{'id': i.node_id, 'selected': bool(i.selected), "
        "'position': [i.position_x, i.position_y], 'scale': i.scale} "
        f"for i in {SCENE}.mixie_moodboard_images if i.node_id and not i.embedded_node_id]"
    )


def png(path, rgb, width=96, height=96):
    """Create a small deterministic reference fixture without imaging deps."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    rows = []
    for y in range(height):
        row = b"".join(bytes(rgb if (x // 16 + y // 16) % 2 else (240, 240, 240))
                       for x in range(width))
        rows.append(b"\0" + row)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" +
                     chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
                     chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
    return str(path)


def drop(qa, path, **where):
    before = {i["id"] for i in media(qa)}
    qa.cmd("drop_file", path=path, **where)
    qa.wait(f"any(i.node_id and i.node_id not in {list(before)!r} for i in "
            f"{SCENE}.mixie_moodboard_images if not i.embedded_node_id)", timeout=12)
    added = {i["id"] for i in media(qa)} - before
    require(len(added) == 1, f"One file drop added ambiguous media: {added}")
    node_id = added.pop()
    settle(qa, 1)
    qa.wait(f"len(drv.find(surface='moodboard_media', text={node_id!r})) == 1", timeout=8)
    return node_id


def select(qa, node_id):
    qa.click(surface="moodboard_media", text=node_id)
    qa.wait(f"any(i.node_id == {node_id!r} and i.selected for i in "
            f"{SCENE}.mixie_moodboard_images)", timeout=4)
    require(geometry(qa)["amount"] > 0.98, "Selecting media closed the drawer")


def invalid_drop(qa, where):
    path = OUT / "invalid-reference.png"
    path.write_bytes(b"This is not a valid PNG image.\n")
    before = media(qa)
    qa.cmd("drop_file", path=str(path), **where)
    # A failed decoder adds no media and has no positive completion state.
    # Give the real queued drop event a full second to produce its report.
    qa.wait(f"__import__('time').monotonic() >= {time.monotonic() + 1.0}", timeout=3)
    require(media(qa) == before, "Failed image decode left a half-created reference")
    require(geometry(qa)["amount"] < 0.02, "Failed image decode opened the drawer")


def verify_viewport(qa, before):
    after = geometry(qa)
    for key in ("area", "viewport", "view", "objects"):
        require(before[key] == after[key],
                f"Moodboard interaction changed viewport {key}: {before[key]} -> {after[key]}")


def move_pan_zoom(qa, node_id):
    before = next(i for i in media(qa) if i["id"] == node_id)
    widget = target(qa, "moodboard_media", text=node_id)
    start = point(widget)
    qa.cmd("drag", **{"from": {"surface": "moodboard_media", "text": node_id},
                      "to": {"x": start["x"] + 70, "y": start["y"] - 80}, "steps": 10})
    qa.wait(f"any(i.node_id == {node_id!r} and "
            f"[i.position_x, i.position_y] != {before['position']!r} "
            f"for i in {SCENE}.mixie_moodboard_images)", timeout=4)

    state = next(i for i in media(qa) if i["id"] == node_id)
    widget = target(qa, "moodboard_media", text=node_id)
    start = point(widget)
    qa.cmd("drag", **{"from": {"surface": "moodboard_media", "text": node_id},
                      "to": {"x": start["x"] - 65, "y": start["y"] + 95},
                      "steps": 10, "button": "MIDDLEMOUSE"})
    panned = target(qa, "moodboard_media", text=node_id)
    require(panned["center"] != widget["center"], "MMB pan did not move canvas pixels")
    require(next(i for i in media(qa) if i["id"] == node_id)["position"] == state["position"],
            "Panning moved the media in board coordinates")

    select(qa, node_id)
    pre_zoom = target(qa, "moodboard_media", text=node_id)
    qa.press("WHEELUPMOUSE")
    qa.wait(f"any(w['rect'][2] - w['rect'][0] > "
            f"{pre_zoom['rect'][2] - pre_zoom['rect'][0]} for w in "
            f"drv.find(surface='moodboard_media', text={node_id!r}))", timeout=4)
    require(next(i for i in media(qa) if i["id"] == node_id)["scale"] == state["scale"],
            "Zoom changed media scale instead of canvas view")
    select(qa, node_id)


def switch_mode(qa, op, workspace):
    qa.eval(SETUP + "with bpy.context.temp_override(window=win, area=area, region=viewport):\n"
            f"    result = str(bpy.ops.{op}())\n")
    qa.wait(f"drv.main_window().workspace.name == {workspace!r}", timeout=10)


def cancel_generation_dialog(qa):
    # The prompt has autofocus: Esc first exits its text edit. If the popup
    # remains, another Esc dismisses the dialog itself (normal Blender UI).
    qa.press("ESC")
    if qa.find(popup=True, op="MIXIE_OT_imagegen_generate_and_close")["total"]:
        qa.press("ESC")
    qa.wait("not any(w.get('popup') for w in drv.find())", timeout=4)


def extra_media(qa, viewport_at):
    portrait = png(OUT / "reference-portrait.png", (80, 180, 90), width=64, height=768)
    node_id = drop(qa, portrait, **viewport_at)
    # Custom QA targets are clipped to their region. Compare the full image's
    # canvas bounds with View2D, or an offscreen portrait can falsely pass.
    bounds = qa.eval(SETUP +
        "from mixar.modules.moodboard.constants import MOODBOARD_IMAGE_BASE_SIZE\n"
        f"item = next(i for i in win.scene.mixie_moodboard_images if i.node_id == {node_id!r})\n"
        "width = MOODBOARD_IMAGE_BASE_SIZE * item.scale\n"
        "height = width * item.image.size[1] / item.image.size[0]\n"
        "result = {'image': [item.position_x, item.position_y, item.position_x + width, "
        "item.position_y + height], 'view': [*drawer.view2d.region_to_view(0, 0), "
        "*drawer.view2d.region_to_view(drawer.width, drawer.height)]}\n")
    rect, view = bounds["image"], bounds["view"]
    require(view[0] <= rect[0] < rect[2] <= view[2] and
            view[1] <= rect[1] < rect[3] <= view[3],
            f"Portrait is not fully framed: {bounds}")
    select(qa, node_id)
    snap(qa, "08_portrait", True)
    movie_tested = False
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        movie = str(OUT / "reference-video.mp4")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12", "-t", "1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", movie], check=True)
        movie_id = drop(qa, movie, **viewport_at)
        require(qa.eval(f"result = any(i.node_id == {movie_id!r} and "
                        f"i.image.source == 'MOVIE' for i in {SCENE}.mixie_moodboard_images)"),
                "Video drop did not retain its movie source")
        snap(qa, "09_video", True)
        movie_tested = True

    # Supporting operator-state regression: the OS hook cannot emit Image-ID
    # drags. A fresh image_name after file drops must not reuse their filepath.
    qa.eval(SETUP + "image = bpy.data.images.new('QA_DRAWER_IMAGE_ID', 32, 32)\n"
            "with bpy.context.temp_override(window=win, area=area, region=drawer):\n"
            "    bpy.ops.mixie.moodboard_drop_image(image_name=image.name, from_drop=True, "
            "position_x=0, position_y=0)\n"
            f"result = any(i.image == image for i in {SCENE}.mixie_moodboard_images)")
    require(qa.eval(f"result = any(i.image and i.image.name == 'QA_DRAWER_IMAGE_ID' "
                    f"for i in {SCENE}.mixie_moodboard_images)"),
            "Image-ID import reused a prior file payload")
    return {"portrait_framed": True, "video_imported": movie_tested, "image_id_payload": True}


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.step("wait_idle", qa.wait,
            f"{SCENE}.mixie_chat_state in ('IDLE', 'OFFLINE')", timeout=90)
    if geometry(qa)["workspace"] != "Zen Mode":
        qa.step("enter_zen", switch_mode, qa, "mixar.set_ui_mode_ai", "Zen Mode")
    initial = qa.step("initial_geometry", geometry, qa)
    require(initial["amount"] is not None, "Build does not contain the moodboard drawer")
    if initial["amount"] > 0.02:
        qa.step("close_existing_drawer", toggle, qa, 0)
    initial = geometry(qa)
    qa.step("grip_present", target, qa, "moodboard_drawer_grip")
    require(not qa.find(surface="moodboard_drawer_panel")["total"], "Closed drawer has a panel")
    qa.step("snap_closed", snap, qa, "01_closed")

    qa.step("click_reveal", toggle, qa, 1)
    qa.step("panel_visible", target, qa, "moodboard_drawer_panel")
    qa.step("snap_empty", snap, qa, "02_open_empty")
    qa.step("click_close", toggle, qa, 0)
    qa.step("drag_reveal", drag_grip, qa, -1, 1)
    qa.step("drag_close", drag_grip, qa, 1, 0)
    qa.step("full_travel_reveal", drag_grip, qa, -1, 1, 1.2)
    qa.step("close_after_full_travel", toggle, qa, 0)
    qa.step("reveal_keeps_viewport", verify_viewport, qa, initial)

    red = png(OUT / "reference-red.png", (220, 70, 70))
    blue = png(OUT / "reference-blue.png", (50, 130, 230))
    x0, y0, x1, y1 = initial["viewport"]
    viewport_at = {"x": round(x0 + (x1 - x0) * 0.45),
                   "y": round(y0 + (y1 - y0) * 0.6)}
    qa.step("invalid_drop_recovers", invalid_drop, qa, viewport_at)
    qa.step("invalid_drop_keeps_objects", verify_viewport, qa, initial)
    qa.step("snap_invalid_drop", snap, qa, "invalid_drop")
    # Blender's decoder error is a report popup; dismiss it before the next
    # canvas click, otherwise that click only closes the prior error report.
    qa.step("dismiss_invalid_drop_report", qa.press, "ESC")
    qa.step("invalid_report_closed", qa.wait,
            "not any(w.get('popup') for w in drv.find())", timeout=4)
    first = qa.step("viewport_drop_reveals", drop, qa, red,
                    **viewport_at)
    qa.step("drop_keeps_scene_objects", verify_viewport, qa, initial)
    qa.step("snap_viewport_drop", snap, qa, "03_viewport_drop", True)
    qa.step("select_viewport_reference", select, qa, first)

    viewport_again = qa.step("open_viewport_drop_stays_open", drop, qa, blue, **viewport_at)
    qa.step("open_drop_keeps_objects", verify_viewport, qa, initial)
    qa.step("select_open_viewport_reference", select, qa, viewport_again)
    panel = target(qa, "moodboard_drawer_panel")
    upper = qa.step("upper_drawer_drop", drop, qa, red, **point(panel, 0.40, 0.68))
    qa.step("select_above_center_reference", select, qa, upper)
    panel = target(qa, "moodboard_drawer_panel")
    second = qa.step("lower_drawer_drop", drop, qa, blue, **point(panel, 0.40, 0.12))
    qa.step("select_below_center_reference", select, qa, second)
    qa.step("snap_off_center", snap, qa, "04_off_center", True)
    qa.step("move_pan_zoom", move_pan_zoom, qa, second)
    qa.step("snap_canvas_navigation", snap, qa, "05_canvas_navigation", True)
    qa.step("canvas_keeps_viewport", verify_viewport, qa, initial)

    qa.step("reference_context_menu", qa.press, "RIGHTMOUSE")
    qa.step("context_menu_shown", qa.wait,
            "any(w.get('popup') and 'moodboard' in w.get('op', '').lower() "
            "for w in drv.find())", timeout=4)
    qa.step("snap_context_menu", snap, qa, "06_context_menu")
    qa.step("dismiss_context_menu", qa.press, "ESC")
    qa.step("restore_canvas_focus", select, qa, second)
    qa.step("open_features_pie", qa.press, "TAB", ctrl=True)
    qa.step("features_pie_shown", qa.wait,
            "len(drv.find(popup=True, op='MIXIE_OT_imagegen_popup')) == 1", timeout=4)
    qa.step("open_imagegen_popup", qa.click, popup=True, op="MIXIE_OT_imagegen_popup")
    qa.step("imagegen_popup_shown", qa.wait,
            "len(drv.find(popup=True, op='MIXIE_OT_imagegen_generate_and_close')) == 1",
            timeout=5)
    qa.step("snap_generation_popup", snap, qa, "generation_popup")
    qa.step("cancel_generation_popup", cancel_generation_dialog, qa)

    qa.step("close_with_references", toggle, qa, 0)
    qa.step("reopen_keeps_references", toggle, qa, 1)
    require({first, viewport_again, upper, second} <= {i["id"] for i in media(qa)},
            "Reopening lost references")
    qa.step("reselect_after_reopen", select, qa, second)
    qa.step("delete_reference", qa.press, "DEL")
    qa.step("reference_deleted", qa.wait,
            f"not any(i.node_id == {second!r} for i in {SCENE}.mixie_moodboard_images)", timeout=4)
    require(first in {i["id"] for i in media(qa)}, "Delete removed an unselected reference")
    qa.step("snap_deleted", snap, qa, "07_deleted")
    qa.step("delete_keeps_viewport", verify_viewport, qa, initial)
    formats = qa.step("portrait_video_and_image_id", extra_media, qa, viewport_at)
    qa.step("formats_keep_objects", verify_viewport, qa, initial)

    qa.step("enter_engine", switch_mode, qa, "mixar.set_ui_mode_pro", "Layout")
    require(not qa.find(surface="moodboard_drawer_grip")["total"], "Drawer grip leaked into Engine")
    qa.step("return_zen", switch_mode, qa, "mixar.set_ui_mode_ai", "Zen Mode")
    qa.step("grip_returns", target, qa, "moodboard_drawer_grip")
    return {"viewport_stable": True, "file_drop_reveals": True,
            "canvas_interactive": True, "screenshots": str(OUT),
            "remaining_reference": first, **formats}


if __name__ == "__main__":
    run_scenario("moodboard_drawer_e2e", run)
