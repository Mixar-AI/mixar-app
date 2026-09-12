# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Record native QA targets without forcing redraws; measure rendered eye motion."""

import inspect
import math
from pathlib import Path

from PIL import Image

from lib import ScenarioFail


def _capture_in_app(queries, output, duration):
    """Executed by the QA server as a generator so the app keeps animating."""
    import time
    from pathlib import Path

    from PIL import Image
    import qa_driver as drv
    import qa_vision

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    targets = [drv.find_one(drv.snapshot(), **query) for query in queries]
    win = targets[0]["_win"]
    if any(target["window"] != win.as_pointer() for target in targets):
        raise RuntimeError("A motion capture must target one window")
    raw = output / "capture.png"
    sequences = [[] for _ in targets]
    start = time.monotonic()
    try:
        while time.monotonic() - start < duration or len(sequences[0]) < 24:
            # No tag_redraw: a broken animation timer must produce frozen frames.
            qa_vision._capture(win, str(raw))
            elapsed = time.monotonic() - start
            with Image.open(raw) as screenshot:
                for index, query in enumerate(queries):
                    target = drv.find_one(drv.snapshot(), **query)
                    x0, y0, x1, y1 = target["rect"]
                    # Rects are the native framebuffer coordinates, bottom-up.
                    bounds = (x0, screenshot.height - y1, x1, screenshot.height - y0)
                    path = output / f"target_{index}_{len(sequences[index]):04d}.png"
                    screenshot.crop(bounds).save(path)
                    sequences[index].append({"path": str(path), "time": elapsed})
            yield 0.04
    finally:
        raw.unlink(missing_ok=True)
    return sequences


def capture(qa, queries, output, duration=6.5):
    return qa.eval(
        inspect.getsource(_capture_in_app)
        + f"\nresult = _capture_in_app({queries!r}, {str(output)!r}, {duration!r})"
    )


def _features(path):
    with Image.open(path) as image:
        image = image.convert("RGB")
        colored, highlights = [], []
        for index, rgb in enumerate(image.getdata()):
            high, low = max(rgb), min(rgb)
            point = (index % image.width, index // image.width)
            # Bright saturated iris pixels exclude the card's breathing green wash.
            if high > 170 and high - low > 70:
                colored.append(point)
            elif low > 170 and high - low < 35:
                highlights.append(point)
        return image.size, colored, highlights


def _centroid(points):
    return tuple(sum(point[axis] for point in points) / len(points) for axis in (0, 1))


def verify(sequence, *, blink=False, still=False):
    samples = [_features(frame["path"]) for frame in sequence]
    if len(samples) < 12 or len({size for size, _, _ in samples}) != 1:
        raise ScenarioFail("Motion capture needs 12+ frames with stable target dimensions")
    areas = [len(colored) for _, colored, _ in samples]
    peak = max(areas)
    if peak < 8:
        raise ScenarioFail("No crisp luminous eyes rendered inside the cat target")
    signatures = {(tuple(colored), tuple(highlights)) for _, colored, highlights in samples}
    if still:
        if len(signatures) != 1:
            raise ScenarioFail("A settled cat's eyes kept changing")
        return {"frames": len(samples), "still": True}

    offsets = []
    for _, colored, highlights in samples:
        if len(colored) > peak * 0.60 and len(highlights) >= 2:
            eye, shine = _centroid(colored), _centroid(highlights)
            offsets.append((shine[0] - eye[0], shine[1] - eye[1]))
    if len(offsets) < 4:
        raise ScenarioFail("Too few open eyes to measure pupil movement")
    # Measure highlights relative to the iris: breathing or head travel alone
    # cannot pass this check when pupils are frozen in their eye sockets.
    travel = math.hypot(*(max(v[i] for v in offsets) - min(v[i] for v in offsets)
                          for i in (0, 1)))
    if travel < min(samples[0][0]) * 0.012:
        raise ScenarioFail(f"Pupils barely moved inside their eyes: {travel:.2f}px")
    blink_ratio = min(areas) / peak
    if blink and blink_ratio > 0.35:
        raise ScenarioFail(f"No closed blink captured: minimum eye area {blink_ratio:.2%}")
    return {"frames": len(samples), "pupil_travel_px": round(travel, 2),
            "minimum_eye_area_ratio": round(blink_ratio, 3)}


def preview(sequence, path):
    """Package the actual captured frames at their recorded cadence for review."""
    frames = []
    for sample in sequence:
        with Image.open(sample["path"]) as image:
            frames.append(image.convert("RGB"))
    durations = [max(20, round((b["time"] - a["time"]) * 1000))
                 for a, b in zip(sequence, sequence[1:])]
    durations.append(durations[-1])
    try:
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=durations, loop=0, disposal=2)
    finally:
        for frame in frames:
            frame.close()
    return str(Path(path))
