# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Headless proof that an uploaded reference keeps its colours and format.

Run inside the built app (or stock Blender), no backend and no credits::

    <Mixar.app>/Contents/MacOS/Mixar -b --python tests/qa/upload_encoder_blender_smoke.py

``compress_image_for_upload`` encodes through ``Image.save_render``, which
takes format AND colour management from a scene. On the user's scene that
was PNG / RGBA through the AgX view transform, so every reference the desktop
uploaded reached the vendor tone-mapped (white 255 → 197) and as a PNG
labelled JPEG. This writes synthetic PNGs with known flat colours, runs the
real encoder from ``src/`` and checks:

- an opaque image is a real JPEG at the requested quality whose block
  colours match the source (JPEG tolerance), white staying white;
- an image with transparency stays an RGBA PNG with its alpha intact;
- the longest side is capped at ``max_dimension``;
- the throwaway export scene is gone afterwards and the user's scene settings
  are untouched.

Prints one ``__RESULT__`` JSON line and exits 1 on any failure.
"""

import importlib.util
import json
import os
import struct
import sys
import traceback
import zlib

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src", "scripts")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

BLOCKS = ((255, 0, 0), (128, 128, 128), (255, 255, 255), (30, 60, 220))
JPEG_TOLERANCE = 6


def _load_src(dotted: str):
    path = os.path.join(SRC, *dotted.split(".")) + ".py"
    spec = importlib.util.spec_from_file_location(dotted, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    spec.loader.exec_module(module)
    return module


def _png(width, height, pixel, *, alpha=False):
    """A PNG of ``width``x``height`` whose pixel (x, y) is ``pixel(x, y)``."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row += bytes(pixel(x, y))
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def _write(path, data):
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _decoded(data, suffix, workdir):
    """Load ``data`` back through Blender and return (image, sampler)."""
    path = _write(os.path.join(workdir, f"decoded{suffix}"), data)
    image = bpy.data.images.load(path, check_existing=False)
    pixels = image.pixels[:]
    channels = image.channels
    width, height = image.size

    def at(x, y):
        # PNG row 0 is the top; Blender's pixel row 0 is the bottom.
        index = ((height - 1 - y) * width + x) * channels
        return tuple(round(v * 255) for v in pixels[index:index + channels])

    return image, at


def _close(actual, expected, tolerance):
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


def main():
    import tempfile

    image_utils = _load_src("mixar.modules.common.utils.image_utils")
    workdir = tempfile.mkdtemp(prefix="mixar_upload_smoke_")
    failures = []
    scene = bpy.context.scene
    before = (
        scene.render.image_settings.file_format,
        scene.view_settings.view_transform,
        len(bpy.data.scenes),
    )

    # --- 1. opaque blocks → JPEG, colours preserved ---------------------
    size = 64
    opaque = _write(os.path.join(workdir, "opaque.png"), _png(
        size, size, lambda x, y: BLOCKS[(y // 32) * 2 + (x // 32)]))
    source = bpy.data.images.load(opaque, check_existing=False)
    data = image_utils.compress_image_for_upload(source, 2048, 90)
    if data[:2] != b"\xff\xd8":
        failures.append(f"opaque image is not a JPEG (magic {data[:4]!r})")
    _, at = _decoded(data, ".jpg", workdir)
    centres = {
        "red": (16, 16), "gray": (48, 16), "white": (16, 48), "blue": (48, 48),
    }
    for (name, (x, y)), expected in zip(centres.items(), BLOCKS):
        got = at(x, y)[:3]
        if not _close(got, expected, JPEG_TOLERANCE):
            failures.append(f"{name} {expected} came out {got} — view transform applied?")

    # --- 2. transparency → RGBA PNG, alpha intact -------------------------
    cutout = _write(os.path.join(workdir, "cutout.png"), _png(
        size, size, lambda x, y: (255, 0, 0, 255) if x < 32 else (0, 0, 0, 0),
        alpha=True))
    source = bpy.data.images.load(cutout, check_existing=False)
    data = image_utils.compress_image_for_upload(source, 2048, 90)
    if not data.startswith(b"\x89PNG"):
        failures.append(f"transparent image is not a PNG (magic {data[:4]!r})")
    else:
        decoded, at = _decoded(data, ".png", workdir)
        if decoded.channels != 4 or at(48, 16)[3] > 2:
            failures.append(f"transparency lost: channels={decoded.channels} alpha={at(48, 16)}")
        if not _close(at(16, 16)[:3], (255, 0, 0), 1):
            failures.append(f"opaque half of the cut-out came out {at(16, 16)}")

    # --- 3. the longest side is capped ------------------------------------
    wide = _write(os.path.join(workdir, "wide.png"), _png(
        256, 32, lambda x, y: (128, 128, 128)))
    source = bpy.data.images.load(wide, check_existing=False)
    data = image_utils.compress_image_for_upload(source, 128, 90)
    decoded, _ = _decoded(data, ".jpg", workdir)
    if tuple(decoded.size) != (128, 16):
        failures.append(f"resize gave {tuple(decoded.size)}, expected (128, 16)")

    # --- 4. the per-service entry point and no scene left behind ----------
    source = bpy.data.images.load(opaque, check_existing=False)
    data = image_utils.compress_for_service(source, "video_gen")
    if data[:2] != b"\xff\xd8":
        failures.append("compress_for_service('video_gen') is not a JPEG")
    after = (
        scene.render.image_settings.file_format,
        scene.view_settings.view_transform,
        len(bpy.data.scenes),
    )
    if after != before:
        failures.append(f"user scene or scene count changed: {before} -> {after}")

    return failures


if __name__ == "__main__":
    try:
        problems = main()
    except Exception:  # noqa: BLE001 — the smoke must always print a result
        problems = [traceback.format_exc()]
    print("__RESULT__ " + json.dumps({"ok": not problems, "failures": problems}))
    sys.exit(1 if problems else 0)
