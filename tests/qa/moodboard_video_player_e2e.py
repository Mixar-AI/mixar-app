#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit: movie card hover controls with sound, and the preview player window.

Launch an isolated Dev app with the QA harness, then run:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/moodboard-video-player \
        python3 tests/qa/moodboard_video_player_e2e.py

Requires ffmpeg (on PATH or in $FFMPEG): a 6 s, 12 fps clip WITH a sine audio
track is generated and dropped into the Zen drawer. Then, through native
clicks:

- the card's centre control plays it and its audio track must be sounding on a
  device (`moodboard_video_sound` value = "playing"); the right control mutes
  and unmutes; the clip plays through and rests on frame 1 with audio stopped;
- the left control opens the preview window, which must autoplay with sound
  and ADVANCE (it used to stay on frame 1); play/pause holds and resumes the
  frame, a timeline click seeks, the volume bar sets the level; there is no
  close control on the picture, and Esc closes the window.

The `*.png` captures must also be viewed: the dimmed card with its three
glyphs, and the player's bottom controls over a moving picture.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from moodboard_drawer_e2e import SCENE, drop, geometry, require, switch_mode, toggle
from moodboard_video_playback_e2e import place

HARNESS = os.environ.get("QA_HARNESS")
if not HARNESS:
    raise SystemExit("Set QA_HARNESS to the local mixar-qa-harness checkout")
sys.path.insert(0, str(Path(HARNESS) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/moodboard-video-player"))
HOST = "VIEW_3D"
CLIP_SECONDS = 6.0
CLIP_FPS = 12
CLIP_FRAMES = int(CLIP_SECONDS * CLIP_FPS)


def clip():
    ffmpeg = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    require(ffmpeg, "This scenario needs ffmpeg (PATH or $FFMPEG) to generate its test clip")
    path = OUT / "player-clip.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate={CLIP_FPS}",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", str(CLIP_SECONDS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return str(path)


def one(qa, surface, **query):
    widgets = qa.find(surface=surface, **query)["widgets"]
    require(len(widgets) == 1, f"Expected one {surface} {query}, got {widgets}")
    return widgets[0]


def snap(qa, name, **target):
    if target:
        qa.cmd("snap", path=str(OUT / f"{name}.png"), target=target)
    else:
        qa.cmd("snap", path=str(OUT / f"{name}.png"), area=HOST)


def card(qa, owner, control="moodboard_video"):
    return one(qa, control, text=owner, area_type=HOST)


def card_audio(owner, state):
    return (f"any(w.get('value') == {state!r} for w in "
            f"drv.find(surface='moodboard_video_sound', text={owner!r}))")


def card_playing(owner, expected=True):
    state = "" if expected else "not "
    return f"{state}any(w.get('sel', False) for w in drv.find(surface='moodboard_video', text={owner!r}))"


def hover(qa, owner):
    """Real pointer motion onto the card: it dims and shows its controls."""
    tile = card(qa, owner)
    qa.eval(f"""
def go():
    win = drv.main_window()
    drv.move_to(win, {tile['center'][0]}, {tile['center'][1] + 30})
    yield .3
    return True
result = go()
""")
    snap(qa, "card-hover")


def card_sound(qa, owner):
    rest = card(qa, owner)
    require(not rest.get("sel", False) and rest["value"] == "1", f"Card not at rest: {rest}")
    qa.click(surface="moodboard_video", text=owner, area_type=HOST)
    qa.wait(card_playing(owner), timeout=3)
    # The bug: no device was open while the scene was idle, so nothing sounded.
    qa.wait(card_audio(owner, "playing"), timeout=3)
    require(not card(qa, owner, "moodboard_video_sound").get("sel", False),
            "Sound must be on by default")
    snap(qa, "card-playing")

    qa.click(surface="moodboard_video_sound", text=owner, area_type=HOST)
    qa.wait(f"any(w.get('sel', False) for w in drv.find(surface='moodboard_video_sound', "
            f"text={owner!r}))", timeout=3)
    require(card(qa, owner).get("sel", False), "Muting must not stop the picture")
    qa.click(surface="moodboard_video_sound", text=owner, area_type=HOST)
    qa.wait(f"not any(w.get('sel', False) for w in drv.find(surface='moodboard_video_sound', "
            f"text={owner!r}))", timeout=3)

    mid = int(card(qa, owner)["value"])
    require(mid > 1, f"Card playback is not advancing: frame {mid}")
    qa.wait(card_playing(owner, False), timeout=CLIP_SECONDS + 4)
    end = card(qa, owner)
    require(end["value"] == "1", f"A finished card must rest on frame 1: {end}")
    qa.wait(card_audio(owner, "stopped"), timeout=2)
    return {"mid_frame": mid}


def player(qa):
    return one(qa, "video_player")


def player_frame_advances(qa, label):
    first = int(player(qa)["value"])
    time.sleep(0.6)
    second = int(player(qa)["value"])
    require(second > first, f"{label}: preview stuck on frame {first} -> {second}")
    return first, second


def player_click(qa, surface, fraction=None):
    """A native click in the player window; on a bar, at `fraction` of its width."""
    w = one(qa, surface)
    x0, y0, x1, y1 = w["rect"]
    x = int(x0 + (x1 - x0) * fraction) if fraction is not None else w["center"][0]
    y = w["center"][1]
    qa.eval(f"""
win = next(w for w in drv.find(surface={surface!r}))['_win']
result = drv.click_xy_steps(win, {x}, {y})
""")


def preview(qa, owner):
    qa.click(surface="moodboard_video_preview", text=owner, area_type=HOST)
    qa.wait("len(drv.find(surface='video_player')) == 1", timeout=10)
    qa.wait("drv.find(surface='video_player')[0].get('sel', False)", timeout=3)
    view = player(qa)
    require(view["index"] == CLIP_FRAMES, f"Player reads {view['index']} frames, not {CLIP_FRAMES}")
    qa.wait("drv.find(surface='video_player')[0].get('detail') == 'playing'", timeout=3)
    advanced = player_frame_advances(qa, "autoplay")
    surfaces = {w.get("surface") for w in qa.find(window=view["window"])["widgets"]}
    require(not any(s and "close" in s for s in surfaces),
            f"The picture must carry no close control: {sorted(s for s in surfaces if s)}")
    snap(qa, "player-playing", surface="video_player")

    player_click(qa, "video_player_play")
    qa.wait("not drv.find(surface='video_player')[0].get('sel', False)", timeout=3)
    held = int(player(qa)["value"])
    time.sleep(0.5)
    require(int(player(qa)["value"]) == held, "A paused preview kept advancing")
    qa.wait("drv.find(surface='video_player')[0].get('detail') == 'stopped'", timeout=2)
    snap(qa, "player-paused", surface="video_player")

    player_click(qa, "video_player_timeline", 0.4)
    seek = int(player(qa)["value"])
    expected = 1 + int(0.4 * CLIP_FRAMES)
    require(abs(seek - expected) <= 3, f"Timeline click at 40% landed on {seek}, not ~{expected}")
    require(not player(qa).get("sel", False), "Seeking a paused preview must not start it")

    player_click(qa, "video_player_volume", 0.5)
    volume = int(one(qa, "video_player_volume")["value"])
    require(40 <= volume <= 60, f"Volume bar click at 50% set {volume}%")

    player_click(qa, "video_player_play")
    qa.wait("drv.find(surface='video_player')[0].get('sel', False)", timeout=3)
    resumed = player_frame_advances(qa, "resume")
    require(resumed[0] >= seek, f"Resume restarted at {resumed[0]}, not from {seek}")

    qa.eval("""
win = drv.find(surface='video_player')[0]['_win']
drv.press(win, 'ESC')
result = True
""")
    qa.wait("len(drv.find(surface='video_player')) == 0", timeout=5)
    return {"autoplay_frames": advanced, "held": held, "seek": seek,
            "volume": volume, "resumed": resumed}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), "Use isolated QA")
    # A fresh launch registers its UI in deferred batches.
    qa.wait(f"hasattr({SCENE}, 'mixie_moodboard_images')", timeout=60)
    require(qa.eval(f"result=len({SCENE}.mixie_moodboard_images)") == 0, "Use a fresh scene")
    if geometry(qa)["workspace"] != "Zen Mode":
        qa.step("enter_zen", switch_mode, qa, "mixar.set_ui_mode_ai", "Zen Mode")
    if geometry(qa)["amount"] < 0.98:
        qa.step("open_drawer", toggle, qa, 1)
    movie = clip()
    tile = qa.step("drop_movie", drop, qa, movie, target={"surface": "moodboard_drawer_panel"})
    qa.step("place", place, qa, HOST, tile)
    qa.step("hover_controls", hover, qa, tile)
    card_result = qa.step("card_plays_with_sound", card_sound, qa, tile)
    player_result = qa.step("preview_player", preview, qa, tile)
    return {"backend_submissions": 0, "card": card_result, "player": player_result}


if __name__ == "__main__":
    run_scenario("moodboard_video_player_e2e", run)
