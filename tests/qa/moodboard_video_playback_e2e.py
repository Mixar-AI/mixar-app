#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit: an inline moodboard movie plays to its end wherever the pointer goes.

Launch an isolated Dev app with the QA harness, then run:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/moodboard-video-playback \
        python3 tests/qa/moodboard_video_playback_e2e.py

Requires ffmpeg: a 2 s, 12 fps test clip is generated. An uploaded movie tile
in the Zen drawer and in the standalone Moodboard editor, and a movie inside a
generated node card (fixture, nothing submitted), are each started with a
native click on their play disc. The pointer then leaves the tile -- empty
canvas, headers, the viewport, the top bar -- and the movie must keep
advancing, then stop by itself on frame 1 once the clip has played through.
A mid-way click pauses and the next one resumes from that frame.

State comes from the `moodboard_video` QA target (`sel` = playing, `value` =
current frame). The `*-playing` / `*-finished` screenshots must also be viewed:
a pause glyph over a moving frame, then the play glyph over the first frame.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from moodboard_drawer_e2e import (  # noqa: E402
    SCENE, SETUP, drop, geometry, require, switch_mode, target, toggle,
)

HARNESS = os.environ.get("QA_HARNESS")
if not HARNESS:
    raise SystemExit("Set QA_HARNESS to the local mixar-qa-harness checkout")
sys.path.insert(0, str(Path(HARNESS) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/moodboard-video-playback"))
CLIP_SECONDS = 2.0
CLIP_FPS = 12


def clip():
    ffmpeg = shutil.which("ffmpeg")
    require(ffmpeg, "This scenario needs ffmpeg to generate its test clip")
    path = OUT / "playback-clip.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc2=size=320x180:rate={CLIP_FPS}", "-t", str(CLIP_SECONDS),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def canvas_kind(host):
    return "TOOL_PROPS" if host == "VIEW_3D" else "WINDOW"


def snap(qa, name, host):
    qa.cmd("snap", path=str(OUT / f"{name}.png"), area=host)


def disc(qa, owner, host):
    return target(qa, "moodboard_video", text=owner, area_type=host)


def playing(owner, expected=True):
    # Custom QA targets omit `sel` when false. Missing means stopped.
    state = "" if expected else "not "
    return f"{state}any(w.get('sel', False) for w in drv.find(surface='moodboard_video', text={owner!r}))"


def place(qa, host, owner):
    """Fixture placement: centre the tile or card at half the canvas width."""
    qa.eval(f"""
from mixar.modules.moodboard.constants import MOODBOARD_IMAGE_BASE_SIZE
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == {host!r})
region = next(r for r in area.regions if r.type == {canvas_kind(host)!r})
a = region.view2d.region_to_view(0, 0)
b = region.view2d.region_to_view(region.width, region.height)
w = (b[0] - a[0]) * 0.5
cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
scene = win.scene
for item in scene.mixie_moodboard_images:
    if not item.embedded_node_id:
        item.position_x, item.position_y = cx + 100000, cy
for node in scene.mixie_moodboard_action_nodes:
    node.position_x, node.position_y = cx + 100000, cy
media = next((i for i in scene.mixie_moodboard_images if i.node_id == {owner!r}), None)
if media is not None:
    media.scale = w / MOODBOARD_IMAGE_BASE_SIZE
    h = w * media.image.size[1] / max(media.image.size[0], 1)
    media.position_x, media.position_y = cx - w / 2, cy - h / 2
else:
    node = next(n for n in scene.mixie_moodboard_action_nodes if n.node_id == {owner!r})
    node.width, node.height = w, w * 0.75
    node.position_x, node.position_y = cx - w / 2, cy - node.height / 2
area.tag_redraw()
bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
result = True
""")
    qa.wait(f"len(drv.find(surface='moodboard_video', text={owner!r})) == 1", timeout=5)


def fixture_node(qa, movie):
    """A finished Video Gen card owning the clip, as a completed job leaves it."""
    return qa.eval(SETUP + f"""
from mixar.modules.moodboard.core.node_graph import new_node_id
img = bpy.data.images.load({movie!r}, check_existing=False)
assert img.source == 'MOVIE', img.source
node = win.scene.mixie_moodboard_action_nodes.add()
node.node_id = new_node_id()
node.action_type = 'VIDEO_GEN'
node.state = 'SUCCESS'
node.selected = False
node.preview_image = img
item = win.scene.mixie_moodboard_images.add()
item.image = img
item.node_id = new_node_id()
item.embedded_node_id = node.node_id
item.selected = False
area.tag_redraw()
result = node.node_id
""")


def wander(qa, host):
    """Real pointer motion away from the tile: empty canvas corners, the
    area's headers and sidebar, the 3D viewport beside the drawer, the top
    bar -- each of them a place leaving the tile used to stop playback."""
    points = qa.eval(f"""
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == {host!r})
canvas = next(r for r in area.regions if r.type == {canvas_kind(host)!r})
pts = [(canvas.x + 24, canvas.y + 24), (canvas.x + canvas.width - 24, canvas.y + 24),
       (canvas.x + 24, canvas.y + canvas.height - 24)]
for r in area.regions:
    if r.type in ('HEADER', 'TOOL_HEADER', 'UI') and r.width > 8 and r.height > 8:
        pts.append((r.x + r.width // 2, r.y + r.height // 2))
if {host!r} == 'VIEW_3D':
    view = next(r for r in area.regions if r.type == 'WINDOW')
    pts.append((view.x + 40, view.y + view.height // 2))
pts.append((win.width // 2, win.height - 8))
result = pts
""")
    qa.eval(f"""
def wander():
    win = drv.main_window()
    for x, y in {points!r}:
        drv.move_to(win, x, y)
        yield .12
    return True
result = wander()
""")
    return points


def play_through(qa, host, owner, label):
    rest = disc(qa, owner, host)
    require(not rest.get("sel", False) and rest["value"] == "1",
            f"{label}: movie is not at rest on its first frame: {rest}")
    qa.click(surface="moodboard_video", text=owner, area_type=host)
    started = time.monotonic()
    qa.wait(playing(owner), timeout=3)
    points = wander(qa, host)
    mid = disc(qa, owner, host)
    require(mid.get("sel", False), f"{label}: moving the pointer off the tile stopped playback: {mid}")
    require(int(mid["value"]) > 1, f"{label}: playback is not advancing: {mid}")
    snap(qa, f"{host}-{label}-playing", host)
    qa.wait(playing(owner, False), timeout=CLIP_SECONDS + 4)
    elapsed = time.monotonic() - started
    end = disc(qa, owner, host)
    require(end["value"] == "1", f"{label}: a finished movie must rest on frame 1: {end}")
    require(elapsed >= CLIP_SECONDS * 0.8,
            f"{label}: playback stopped after {elapsed:.2f}s, before the "
            f"{CLIP_SECONDS}s clip had played through")
    time.sleep(0.4)
    require(disc(qa, owner, host)["value"] == "1", f"{label}: a finished movie looped")
    snap(qa, f"{host}-{label}-finished", host)
    return {"elapsed_s": round(elapsed, 2), "mid_frame": int(mid["value"]),
            "pointer_points": len(points)}


def pause_resume(qa, host, owner):
    qa.click(surface="moodboard_video", text=owner, area_type=host)
    qa.wait(f"any(w.get('sel', False) and int(w['value']) >= 6 for w in "
            f"drv.find(surface='moodboard_video', text={owner!r}))", timeout=3)
    qa.click(surface="moodboard_video", text=owner, area_type=host)
    qa.wait(playing(owner, False), timeout=3)
    paused = int(disc(qa, owner, host)["value"])
    require(1 < paused, f"Pause rewound the movie to frame {paused}")
    time.sleep(0.5)
    require(int(disc(qa, owner, host)["value"]) == paused, "A paused movie kept advancing")
    qa.click(surface="moodboard_video", text=owner, area_type=host)
    qa.wait(playing(owner), timeout=3)
    resumed = int(disc(qa, owner, host)["value"])
    require(resumed >= paused, f"Resume restarted at {resumed}, not from {paused}")
    qa.wait(playing(owner, False), timeout=CLIP_SECONDS + 3)
    require(disc(qa, owner, host)["value"] == "1", "The resumed movie did not finish")
    return {"paused_frame": paused, "resumed_frame": resumed}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), "Use isolated QA")
    require(qa.eval(f"result=len({SCENE}.mixie_moodboard_images)") == 0, "Use a fresh scene")
    if geometry(qa)["workspace"] != "Zen Mode":
        qa.step("enter_zen", switch_mode, qa, "mixar.set_ui_mode_ai", "Zen Mode")
    if geometry(qa)["amount"] < 0.98:
        qa.step("open_drawer", toggle, qa, 1)
    movie = clip()
    tile = qa.step("drop_movie", drop, qa, movie, target={"surface": "moodboard_drawer_panel"})
    card = qa.step("fixture_video_node", fixture_node, qa, movie)
    results = {}
    for host in ("VIEW_3D", "MIXIE"):
        if host == "MIXIE":
            qa.eval("next(a for a in drv.main_window().screen.areas "
                    "if a.type=='VIEW_3D').type='MIXIE'; result=True")
        for label, owner in (("tile", tile), ("node", card)):
            qa.step(f"{host}-{label}-place", place, qa, host, owner)
            results[f"{host}-{label}"] = qa.step(
                f"{host}-{label}-plays-through-off-tile", play_through, qa, host, owner, label)
        place(qa, host, tile)
        results[f"{host}-pause"] = qa.step(
            f"{host}-pause-and-resume", pause_resume, qa, host, tile)
    qa.eval("next(a for a in drv.main_window().screen.areas "
            "if a.type=='MIXIE').type='VIEW_3D'; result=True")
    return {"backend_submissions": 0, "playback": results}


if __name__ == "__main__":
    run_scenario("moodboard_video_playback_e2e", run)
