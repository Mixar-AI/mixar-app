# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Headless proof that a delivery package writes every texture with the
pixels the image holds now, against the REAL Blender 5.2 image code.

Run inside the built app, no backend and no credits::

    <Mixar.app>/Contents/MacOS/Mixar -b --factory-startup --python tests/qa/package_textures_blender_smoke.py

Four textured cubes, each exported in its OWN GLB package with a 4 px
texture tier (``texture_tiers=(4,)``), so one failure never hides another:

- ``Label`` uses an 8-bit PNG loaded from disk and left unpacked, the way an
  agent script's ``bpy.data.images.load(path)`` leaves it. The package's
  ``Image.copy()`` held no pixels, re-read its source after its path was
  pointed at the PNG it was about to write, and failed with
  ``Image 'label.png_pkg' does not have any image data`` (mixar-backend#2020).
- ``Painted`` uses a generated image whose pixels were set in memory and
  never saved, as paint and the render worker's snapshot restore leave
  them; the copy came back black.
- ``Deep`` uses a 16-bit sRGB PNG loaded unpacked (a float buffer held in
  scene linear); its PNG must read back the source file's value, not a
  colour-shifted one.
- ``GreyAlpha`` uses an 8-bit grey+alpha PNG loaded unpacked
  (``Image.depth`` 16: colour-mode channels x 8); its PNG must keep the
  alpha channel, not come out as RGB darkened by the alpha.

Checks per cube: the package succeeds, and ``textures/`` and
``textures_4/`` each hold its PNG reading back the source colour. Packages
go to a temp folder (``where="project"`` with ``set_project_folder``), never
the real ~/Documents, and package telemetry is off. The ``src/`` modules are
loaded over the bundle's copies by file, so this proves the working tree.
Prints one ``__RESULT__`` JSON line.
"""

import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
import traceback
import zlib

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src", "scripts")
CORE = "mixar.modules.space_mixie_chat.core"
SRC_MODULES = tuple(f"{CORE}.{m}" for m in (
    "export_verification_status", "export_gltf_bounds", "export_verify", "export_clips",
    "export_materials", "export_bake_cache", "export_bake", "engine_targets", "export_package",
))
LABEL_RGB = (0.2, 0.6, 0.4)
PAINT_RGB = (0.8, 0.3, 0.1)
DEEP_RGB = (0.3, 0.5, 0.7)
GREY_ALPHA = (76, 128)  # 8-bit grey, alpha
TIER = 4


def _load_src(dotted: str):
    path = os.path.join(SRC, *dotted.split(".")) + ".py"
    spec = importlib.util.spec_from_file_location(dotted, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    spec.loader.exec_module(module)
    return module


def _textured_cube(name, image, x):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, 0, 0))
    obj = bpy.context.object
    obj.name = name
    mat = bpy.data.materials.new(name + "_mat")
    tree = mat.node_tree
    tex = tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tree.links.new(tex.outputs["Color"], tree.nodes["Principled BSDF"].inputs["Base Color"])
    obj.data.materials.append(mat)
    return obj


def _png_px(path, channels=3):
    """First pixel of a PNG (byte buffers hold straight alpha)."""
    img = bpy.data.images.load(path, check_existing=False)
    px = img.pixels[:4]
    bpy.data.images.remove(img)
    return tuple(round(v, 2) for v in px[:channels])


def _close(a, b):
    return len(a) == len(b) and all(abs(x - y) < 0.02 for x, y in zip(a, b))


def _png_file(path, rgb, float_buffer=False):
    """An 8x8 PNG on disk (16-bit when ``float_buffer``), loaded unpacked."""
    src = bpy.data.images.new("fixture_src", 8, 8, float_buffer=float_buffer)
    src.pixels.foreach_set([*rgb, 1.0] * 64)
    src.filepath_raw = path
    src.file_format = "PNG"
    src.save()
    bpy.data.images.remove(src)
    return bpy.data.images.load(path, check_existing=False)


def _grey_alpha_png_file(path, grey, alpha):
    """An 8x8 8-bit grey+alpha PNG on disk, loaded unpacked. Written by hand:
    Blender saves a grey+alpha image as RGBA."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    rows = (b"\x00" + bytes((grey, alpha)) * 8) * 8
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 4, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return bpy.data.images.load(path, check_existing=False)


def _package(package, work, obj_name, png, expected):
    """Export one cube in its own package -> (checks, error, written)."""
    stem = f"smoke_{obj_name.lower()}"
    root = package.destination("project", stem, create=False)
    error, res, written = "", {}, {}
    try:
        res = package.export_package([obj_name], fmt="glb", filename=stem, where="project",
                                     texture_tiers=(TIER,))
        for d in ("textures", f"textures_{TIER}"):
            written[d] = _png_px(os.path.join(root, d, png), len(expected))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    checks = {
        f"{obj_name}_in_temp": root.startswith(work),
        f"{obj_name}_succeeded": not error and res.get("textures") == 1 and len(res.get("tiers") or ()) == 1,
        f"{obj_name}_pixels": _close(written.get("textures", ()), expected),
        f"{obj_name}_tier_pixels": _close(written.get(f"textures_{TIER}", ()), expected),
    }
    return checks, error, written


def main() -> dict:
    sys.path.insert(0, SRC)
    for dotted in SRC_MODULES:
        _load_src(dotted)
    package = sys.modules[f"{CORE}.export_package"]

    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.data.use_autopack = False
    work = tempfile.mkdtemp(prefix="mixar_pkg_tex_")
    package.set_project_folder(work)
    package.set_telemetry_enabled(False)
    label = _png_file(os.path.join(work, "label.png"), LABEL_RGB)
    deep_path = os.path.join(work, "deep.png")
    deep = _png_file(deep_path, DEEP_RGB, float_buffer=True)
    with open(deep_path, "rb") as fh:
        deep_bit_depth = fh.read(25)[24]
    deep_rgb = _png_px(deep_path)  # the source file's value, read the same way as the output
    grey_alpha = _grey_alpha_png_file(os.path.join(work, "grey_alpha.png"), *GREY_ALPHA)
    grey, alpha = (v / 255 for v in GREY_ALPHA)
    grey_alpha_px = (grey, grey, grey, alpha)
    painted = bpy.data.images.new("painted", 8, 8)
    painted.pixels.foreach_set([*PAINT_RGB, 1.0] * 64)
    _textured_cube("Label", label, 0.0)
    _textured_cube("Painted", painted, 2.0)
    _textured_cube("Deep", deep, 4.0)
    _textured_cube("GreyAlpha", grey_alpha, 6.0)

    checks = {
        "fixture_unpacked": label.packed_file is None and deep.packed_file is None
        and grey_alpha.packed_file is None,
        "fixture_16bit_srgb": deep_bit_depth == 16 and deep.is_float
        and deep.colorspace_settings.name == "sRGB",
        "fixture_grey_alpha": grey_alpha.depth == 16 and not grey_alpha.is_float
        and _close(tuple(grey_alpha.pixels[:4]), grey_alpha_px),
    }
    errors, written = {}, {}
    try:
        for obj_name, png, expected in (("Label", "label.png", LABEL_RGB),
                                        ("Painted", "painted.png", PAINT_RGB),
                                        ("Deep", "deep.png", deep_rgb),
                                        ("GreyAlpha", "grey_alpha.png", grey_alpha_px)):
            case_checks, error, written[obj_name] = _package(package, work, obj_name, png, expected)
            checks.update(case_checks)
            if error:
                errors[obj_name] = error
    finally:
        package.set_project_folder(None)
        shutil.rmtree(work, ignore_errors=True)
    checks["no_leftover_copies"] = not [
        i.name for i in bpy.data.images if i.name.endswith(("_pkg", f"_{TIER}"))]
    return {"ok": all(checks.values()), "checks": checks, "errors": errors, "written": written}


if __name__ == "__main__":
    try:
        out = main()
    except Exception:
        out = {"ok": False, "error": traceback.format_exc()}
    print("__RESULT__ " + json.dumps(out))
    sys.stdout.flush()
