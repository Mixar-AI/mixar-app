#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verify actual tier eye colors in an isolated QA app; zero credit spend.

QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/cat-tier-colors \
    python3 tests/qa/cat_tier_colors_e2e.py
Read comparison.png alongside verdict.json. Account fixtures stay local.
"""

from collections import Counter
from colorsys import rgb_to_hsv
import inspect
from itertools import combinations
import json
import os
from pathlib import Path
from statistics import mean
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario  # noqa: E402


PALETTES = ["Emerald", "Amber", "Rose", "Lilac", "Sky", "Coral"]
HUES = [142, 37, 333, 262, 207, 8]


def _record(tier, output, working=False):
    """Use the login mirror and capture real frames across a possible blink."""
    import bpy
    import qa_driver as drv
    from pathlib import Path
    from mixar.modules.common.usage.core.account import apply_from_user_info

    apply_from_user_info({"data": {"name": "QA", "subscription_type": tier}})
    assert bpy.context.window_manager.mixar_subscription_type == tier
    queue = bpy.context.window_manager.mixie_queue.items
    if working:
        item = queue.add()
        item.job_id = "qa-cat-chip"
        item.state = "RUNNING"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frames = []
    try:
        yield .4
        for index in range(22 if working else 8):
            target = drv.find_one(surface="pill_cat")
            assert target["value"] == ("Generating" if working else "Idle")
            win = target["_win"]
            x0, y0, x1, y1 = target["rect"]
            path = output / f"frame-{index}.png"
            with bpy.context.temp_override(window=win):
                assert win.mixar_qa_capture_frame(
                    filepath=str(path), x=x0, y=y0, width=x1-x0, height=y1-y0)
                assert win.mixar_qa_capture_frame(filepath=str(path.with_suffix(".pill.png")))
            frames.append(str(path))
            yield .1
    finally:
        for i in reversed(range(len(queue))):
            if queue[i].job_id == "qa-cat-chip":
                queue.remove(i)
    return frames


def eye_hue(path):
    with Image.open(path) as image:
        # The brightest chip stop, even at the activity peak, stays below 195.
        buckets = Counter(
            int(rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 72) % 72
            for r, g, b in image.convert("RGB").getdata()
            if max(r, g, b) > 195 and max(r, g, b) - min(r, g, b) > 70
        )
    if not buckets:
        return 0, 0
    bucket, count = buckets.most_common(1)[0]
    return count, bucket * 5 + 2.5


def hue_distance(a, b):
    delta = abs(a - b)
    return min(delta, 360 - delta)


def chip_samples(path):
    """Sample inset side patches outside the cat using its native chip bounds."""
    with Image.open(path) as image:
        image = image.convert("RGB")
        def patch(x):
            cx, cy = int(image.width*x), image.height//2
            pixels = list(image.crop((cx-1, cy-2, cx+2, cy+3)).getdata())
            return tuple(mean(pixel[channel] for pixel in pixels) for channel in range(3))
        return patch(.09), patch(.91)


def verify_chip(frames, expected_hue, working):
    samples = [chip_samples(path) for path in frames]
    for left, right in samples:
        assert max(left)-max(right) >= 20, (left, right)  # Visible diagonal falloff.
        for color in (left, right):
            h, saturation, value = rgb_to_hsv(*(c/255 for c in color))
            assert hue_distance(h*360, expected_hue) < 20, (h*360, expected_hue)
            assert saturation > .20 and .20 < value < .77, color
    values = [max(left) for left, _ in samples]
    variation = max(values)-min(values)
    if working:
        assert variation >= 4, f"No visible chip pulse: {variation}"
    else:
        assert variation < 1, f"Idle chip changed: {variation}"
    return dict(left_rgb=samples[0][0], right_rgb=samples[0][1], pulse_range=variation)


def run(qa):
    out = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/cat-tier-colors"))
    out.mkdir(parents=True, exist_ok=True)
    qa.step("ready", qa.cmd, "wait_login", timeout=60)
    qa.step("connected_idle", qa.wait,
            "drv.main_window().scene.mixie_chat_state == 'IDLE'", timeout=30)
    saved = qa.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA app'
wm = bpy.context.window_manager
scene = drv.main_window().scene
assert not scene.mixie_chat_is_busy
result = dict(tier=wm.mixar_subscription_type, name=wm.mixar_account_name)
""")
    rows, images, pills = [], [], []
    try:
        qa.eval("bpy.ops.mixar.bubble_minimise(); result = True")
        qa.wait("bool(drv.find(surface='pill_cat'))", timeout=10)
        qa.wait("drv.find_one(surface='pill_cat')['value'] == 'Idle'", timeout=10)
        for tier in [0, 1, 2, 3, 4, 5, 99]:
            frames = qa.step(f"tier_{tier}", qa.eval, inspect.getsource(_record)
                + f"\nresult = _record({tier}, {str(out / str(tier))!r})")
            count, hue, path = max((*eye_hue(path), path) for path in frames)
            assert count >= 8, f"Tier {tier}: no readable luminous eyes"
            expected = tier if tier in range(6) else 0
            assert hue_distance(hue, HUES[expected]) < 15, (tier, hue)
            rows.append(dict(tier=tier, palette=PALETTES[expected], hue=hue,
                             iris_pixels=count, image=path,
                             chip=verify_chip(frames, HUES[expected], False)))
            with Image.open(path) as image:
                images.append(image.convert("RGB"))
            busy_frames = qa.step(f"tier_{tier}_working", qa.eval, inspect.getsource(_record)
                + f"\nresult = _record({tier}, {str(out / f'{tier}-working')!r}, True)")
            rows[-1]["working_chip"] = verify_chip(busy_frames, HUES[expected], True)
            _, busy_hue, busy_path = max((*eye_hue(p), p) for p in busy_frames)
            assert hue_distance(busy_hue, HUES[expected]) < 15
            pills.append((str(Path(path).with_suffix(".pill.png")),
                          str(Path(busy_path).with_suffix(".pill.png"))))
        for row in rows[1:6]:
            assert hue_distance(row["hue"], rows[0]["hue"]) >= 60, row
        for a, b in combinations(rows[:6], 2):
            assert hue_distance(a["hue"], b["hue"]) >= 20, (a, b)

        sheet = Image.new("RGB", (len(rows) * 150, 220), "#191919")
        draw = ImageDraw.Draw(sheet)
        for i, (row, image) in enumerate(zip(rows, images)):
            x = i * 150
            title = "Free" if row["tier"] == 0 else f"Tier {row['tier']}"
            if row["tier"] == 4:
                title = "Trial"
            if row["tier"] == 99:
                title = "Unknown"
            draw.text((x + 10, 10), title + " / " + row["palette"], fill="white")
            sheet.paste(image, (x + (150-image.width)//2, 40))
            # Logical-size companion for readability at the actual pill scale.
            small = image.resize((image.width//2, image.height//2), Image.Resampling.LANCZOS)
            sheet.paste(small, (x + (150-small.width)//2, 140))
        sheet.save(out / "comparison.png")
        with Image.open(pills[0][0]) as image:
            pill_w, pill_h = image.size
        overview = Image.new("RGB", ((pill_w+24)*2, (pill_h+36)*len(rows)), "#191919")
        draw = ImageDraw.Draw(overview)
        for i, (row, paths) in enumerate(zip(rows, pills)):
            for j, path in enumerate(paths):
                x, y = j*(pill_w+24)+12, i*(pill_h+36)
                draw.text((x+12, y+7), f"{row['palette']} / {'Working' if j else 'Idle'}",
                          fill="white")
                with Image.open(path) as image:
                    overview.paste(image.convert("RGB"), (x, y+28))
        overview.save(out / "pill_comparison.png")
        verdict = dict(tiers=rows, paid_requests=0,
                       comparison=str(out / "comparison.png"),
                       pill_comparison=str(out / "pill_comparison.png"))
        (out / "verdict.json").write_text(json.dumps(dict(ok=True, **verdict), indent=2) + "\n")
        return verdict
    finally:
        qa.eval(f"""
from mixar.modules.common.usage.core.account import _tag_bubble_redraw
wm = bpy.context.window_manager
wm.mixar_subscription_type = {saved['tier']!r}
wm.mixar_account_name = {saved['name']!r}
_tag_bubble_redraw()
result = True
""")


if __name__ == "__main__":
    run_scenario("cat_tier_colors_e2e", run)
