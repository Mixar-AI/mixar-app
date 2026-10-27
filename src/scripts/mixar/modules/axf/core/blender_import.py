# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Turn an AxF CarPaint2 file into a Blender material that renders it exactly.

Lossless by construction:
- the native AxF Car Paint BSDF evaluates X-Rite's CarPaint2 model in Cycles;
- its data images are float32 EXRs packed into the .blend (bit-exact);
- the original .axf bytes are packed too, so export_axf() writes back the
  identical file (same SHA-256).
"""

from __future__ import annotations

import json
import os
import tempfile

import bpy
import numpy as np

from mixar.config.logging_config import get_logger

from .. import constants as C
from .cpa2_reader import read_cpa2, sha256_file
from .payload import build_payload, preview_inputs

logger = get_logger(__name__)


def _write_exr(path: str, image_rows: np.ndarray, *, half: bool = False) -> None:
    """Write float RGBA (or half RGB); image_rows[0] is the row Cycles reads first."""
    import OpenImageIO as oiio

    if half:
        image_rows = image_rows[..., :3]
    h, w, ch = image_rows.shape
    spec = oiio.ImageSpec(w, h, ch, oiio.HALF if half else oiio.FLOAT)
    spec.attribute("compression", "zip")
    out = oiio.ImageOutput.create(path)
    if out is None or not out.open(path, spec):
        raise OSError(f"Cannot write {os.path.basename(path)}")
    try:
        # EXR rows run top-down; Blender's pixel rows run bottom-up.
        pixels = np.ascontiguousarray(image_rows[::-1], np.float16 if half else np.float32)
        if not out.write_image(pixels):
            raise OSError(f"Cannot write {os.path.basename(path)}")
    finally:
        out.close()


def _packed_data_image(name: str, image_rows: np.ndarray, tmpdir: str):
    path = os.path.join(tmpdir, bpy.path.clean_name(name) + ".exr")
    # Half RGB when that is exact (flake patches are stored as halves in the AxF).
    rgb = image_rows[..., :3]
    half = bool(np.all(image_rows[..., 3] == 1.0)
                and np.array_equal(rgb.astype(np.float16).astype(np.float32), rgb))
    _write_exr(path, image_rows, half=half)
    image = bpy.data.images.load(path, check_existing=False)
    image.name = name
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = 'CHANNEL_PACKED'
    image.pack()
    return image


def _archive_source(path: str, name: str):
    """Pack the original .axf bytes; never rendered, only kept for export."""
    archive = bpy.data.images.load(path, check_existing=False)
    archive.name = f"AxF Source: {name}"
    archive.pack()
    archive.use_fake_user = True
    return archive


def _link(nt, a, out, b, inp):
    nt.links.new(a.outputs[out], b.inputs[inp])


def _flake_coordinates(nt, patch_m: float, x: float, y: float):
    """Object-space coordinates projected on the dominant normal axis, in patch units.

    One projection per point (no blending), so flake statistics stay exactly the
    measured ones. Object scale is assumed to be 1 (metres)."""
    nodes = nt.nodes
    tc = nodes.new("ShaderNodeTexCoord"); tc.location = (x - 900, y)
    sp = nodes.new("ShaderNodeSeparateXYZ"); sp.location = (x - 700, y + 120)
    sn = nodes.new("ShaderNodeSeparateXYZ"); sn.location = (x - 700, y - 120)
    _link(nt, tc, "Object", sp, 0)
    _link(nt, tc, "Normal", sn, 0)

    def math(op, a, b=None, loc=(0, 0)):
        n = nodes.new("ShaderNodeMath"); n.operation = op; n.location = loc
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    ax = math('ABSOLUTE', sn.outputs[0], loc=(x - 500, y - 60))
    ay = math('ABSOLUTE', sn.outputs[1], loc=(x - 500, y - 120))
    az = math('ABSOLUTE', sn.outputs[2], loc=(x - 500, y - 180))
    z_ge_x = math('GREATER_THAN', az, ax, loc=(x - 330, y - 60))
    z_ge_y = math('GREATER_THAN', az, ay, loc=(x - 330, y - 120))
    z_dom = math('MULTIPLY', z_ge_x, z_ge_y, loc=(x - 180, y - 90))
    x_ge_y = math('GREATER_THAN', ax, ay, loc=(x - 330, y - 180))
    not_z = math('SUBTRACT', 1.0, z_dom, loc=(x - 180, y - 150))
    x_dom = math('MULTIPLY', not_z, x_ge_y, loc=(x - 60, y - 150))
    # u = Px unless x-dominant (then Py); v = Py if z-dominant else Pz
    u = math('ADD', math('MULTIPLY', math('SUBTRACT', 1.0, x_dom, loc=(x + 60, y + 60)),
                         sp.outputs[0], loc=(x + 180, y + 60)),
             math('MULTIPLY', x_dom, sp.outputs[1], loc=(x + 180, y)), loc=(x + 300, y + 30))
    v = math('ADD', math('MULTIPLY', z_dom, sp.outputs[1], loc=(x + 180, y - 60)),
             math('MULTIPLY', not_z, sp.outputs[2], loc=(x + 180, y - 120)), loc=(x + 300, y - 90))
    comb = nodes.new("ShaderNodeCombineXYZ"); comb.location = (x + 420, y)
    nt.links.new(u, comb.inputs[0]); nt.links.new(v, comb.inputs[1])
    scale = nodes.new("ShaderNodeVectorMath"); scale.operation = 'SCALE'; scale.location = (x + 560, y)
    scale.inputs["Scale"].default_value = 1.0 / patch_m
    _link(nt, comb, 0, scale, 0)
    return scale.outputs[0]


def build_material(m: dict, table_img, flakes_img, *, name: str):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (500, 0)
    axf = nt.nodes.new(C.NODE_IDNAME); axf.location = (200, 0)
    axf.name = axf.label = "AxF Car Paint"
    _link(nt, axf, 0, out, "Surface")

    prev = preview_inputs(m)
    axf.inputs["Preview Diffuse"].default_value = (*prev["diffuse"], 1.0)
    axf.inputs["Preview Specular"].default_value = (*prev["specular"], 1.0)
    axf.inputs["Preview Roughness"].default_value = prev["roughness"]
    axf.inputs["Coat IOR"].default_value = prev["coat_ior"]

    axf[C.PROP_TABLE] = table_img
    if flakes_img is not None:
        axf[C.PROP_FLAKES] = flakes_img
        patch_m = (m["patch_mm"][0] or 25.6) / 1000.0
        nt.links.new(_flake_coordinates(nt, patch_m, -200, 0), axf.inputs["Flake UV"])
    return mat


def import_axf(path: str, *, archive_source: bool = True) -> bpy.types.Material:
    m = read_cpa2(path, load_flakes=True)
    payload = build_payload(m)
    base = m["name"] or os.path.splitext(os.path.basename(path))[0]
    with tempfile.TemporaryDirectory(prefix="mixar_axf_") as tmp:
        table_img = _packed_data_image(f"AxF {base} Table", payload["table_image"], tmp)
        flakes_img = None
        if payload["flake_atlas"] is not None:
            flakes_img = _packed_data_image(f"AxF {base} Flakes", payload["flake_atlas"], tmp)

    mat = build_material(m, table_img, flakes_img, name=f"AxF {base}")
    mat[C.PROP_SOURCE_NAME] = os.path.basename(path)
    mat[C.PROP_SOURCE_SHA256] = sha256_file(path)
    mat["axf_model"] = json.dumps({
        "representation": "CarPaint2", "kd": m["kd"], "lobes": m["lobes"].tolist(),
        "ior": m["ior"], "refractive": m["refractive"], "num_theta_f": m["num_theta_f"],
        "num_theta_i": m["num_theta_i"], "lut": m["lut"].tolist(), "patch_mm": list(m["patch_mm"]),
    })
    if archive_source:
        mat[C.PROP_ARCHIVE] = _archive_source(path, os.path.basename(path))
    if m["extra_materials"]:
        logger.warning("[AxF] %s holds %d more materials; imported the first (%s)",
                       os.path.basename(path), len(m["extra_materials"]), m["name"])
    logger.info("[AxF] imported %s as %s", os.path.basename(path), mat.name)
    return mat


def export_axf(material: bpy.types.Material, filepath: str) -> str:
    """Write the packed original AxF back out; returns its SHA-256."""
    archive = material.get(C.PROP_ARCHIVE)
    if archive is None or archive.packed_file is None:
        raise ValueError("This material has no packed AxF source")
    data = bytes(archive.packed_file.data)
    with open(filepath, "wb") as f:
        f.write(data)
    digest = sha256_file(filepath)
    expected = material.get(C.PROP_SOURCE_SHA256)
    if expected and digest != expected:
        raise ValueError("Exported AxF does not match the imported file")
    return digest
