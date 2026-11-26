# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Turn an AxF CarPaint2 or SVBRDF file into a Blender material that renders it exactly.

Lossless by construction:
- the native AxF Car Paint / AxF SVBRDF BSDFs evaluate X-Rite's models in Cycles;
- its data images are float32 EXRs packed into the .blend (bit-exact);
- the original .axf bytes are packed too (optional: Keep Original File), so
  export_axf() writes back the identical file (same SHA-256). The packed copy
  travels with the .blend; remove_archived_sources() strips it before sharing.
"""

from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import bpy
import numpy as np

from mixar.config.logging_config import get_logger

from .. import constants as C
from . import device_fit, eevee_fit
from .cpa2_reader import read_cpa2, sha256_file
from .payload import (
    build_payload,
    build_svbrdf_atlas,
    build_table_image_like,
    preview_inputs,
    svbrdf_preview_inputs,
)
from .svbrdf_reader import SVBRDF, read_svbrdf, representation_class

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
    # EEVEE reads the parameter stream with texel fetches: keep float32 on the GPU too.
    image.use_half_precision = half
    image.pack()
    return image


def _archive_source(path: str, name: str):
    """Pack the original .axf bytes; never rendered, only kept for export."""
    archive = bpy.data.images.load(path, check_existing=False)
    archive.name = f"{C.ARCHIVE_NAME_PREFIX}{name}"
    archive.pack()
    archive.use_fake_user = True
    archive[C.PROP_IS_ARCHIVE] = True
    return archive


def archived_sources() -> list:
    """Every packed original .axf in the file, including ones whose material is gone
    (the fake user keeps them saved). Files from before the marker match by name."""
    return [img for img in bpy.data.images if C.is_source_archive(img)]


def remove_archived_sources() -> int:
    """Delete every packed original .axf from the file. The materials keep rendering
    exactly (they read only their own data images); only export_axf() needs the
    original, and it then refuses. Returns the number of files removed."""
    for mat in bpy.data.materials:
        if C.PROP_ARCHIVE in mat:
            del mat[C.PROP_ARCHIVE]
    images = archived_sources()
    for img in images:
        bpy.data.images.remove(img)
    return len(images)


def _link(nt, a, out, b, inp):
    nt.links.new(a.outputs[out], b.inputs[inp])


def _surface_mapping(nt, x: float, y: float, *, tangent: bool = True):
    """Flake/coat coordinates for a mesh without UVs: one "AxF Box Projection" group node
    (box_projection.py). Returns (object-space metres on the dominant face, world-space
    tangent or None when tangent=False)."""
    from .box_projection import add_box_projection
    return add_box_projection(nt, x, y, tangent=tangent)


def _tile_coordinates(nt, uv_m, size_mm, x: float, y: float):
    """Metres -> tile units of a map that is size_mm = (width, height) millimetres."""
    scale = nt.nodes.new("ShaderNodeVectorMath"); scale.operation = 'MULTIPLY'; scale.location = (x, y)
    nt.links.new(uv_m, scale.inputs[0])
    scale.inputs[1].default_value = (1000.0 / size_mm[0], 1000.0 / size_mm[1], 0.0)
    return scale.outputs[0]


def build_material(m: dict, table_img, flakes_img, *, name: str, coat_img=None, fit_img=None):
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
    if fit_img is not None:
        axf[C.PROP_EEVEE_FIT] = fit_img
    if flakes_img is None and coat_img is None:
        return mat
    uv_m, tangent = _surface_mapping(nt, -1000, 0, tangent=coat_img is not None)
    if flakes_img is not None:
        axf[C.PROP_FLAKES] = flakes_img
        patch_mm = (m["patch_mm"][0] or 25.6, m["patch_mm"][1] or m["patch_mm"][0] or 25.6)
        nt.links.new(_tile_coordinates(nt, uv_m, patch_mm, -100, 120), axf.inputs["Flake UV"])
    if coat_img is not None:
        axf[C.PROP_COAT_NORMAL] = coat_img
        nt.links.new(_tile_coordinates(nt, uv_m, m["coat_normal_mm"], -100, -120), axf.inputs["Coat UV"])
        nt.links.new(tangent, axf.inputs["Tangent"])
    return mat


def _preview_image(name: str, rgb_rows: np.ndarray, tmpdir: str):
    """Half-float preview texture for EEVEE (never read by Cycles' exact path)."""
    path = os.path.join(tmpdir, bpy.path.clean_name(name) + ".exr")
    _write_exr(path, np.concatenate([rgb_rows, np.ones_like(rgb_rows[..., :1])], -1), half=True)
    image = bpy.data.images.load(path, check_existing=False)
    image.name = name
    image.colorspace_settings.name = "Non-Color"
    image.pack()
    return image


def build_svbrdf_material(m: dict, atlas_img, preview_img, *, name: str):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (500, 0)
    axf = nt.nodes.new(C.SVBRDF_NODE_IDNAME); axf.location = (200, 0)
    axf.name = axf.label = "AxF SVBRDF"
    _link(nt, axf, 0, out, "Surface")
    axf[C.PROP_ATLAS] = atlas_img

    prev = svbrdf_preview_inputs(m)
    axf.inputs["Preview Specular"].default_value = (*prev["specular"], 1.0)
    axf.inputs["Preview Roughness"].default_value = prev["roughness"]

    uv_m, tangent = _surface_mapping(nt, -1000, 0)
    uv = _tile_coordinates(nt, uv_m, m["size_mm"], -100, 120)
    nt.links.new(uv, axf.inputs["UV"])
    nt.links.new(tangent, axf.inputs["Tangent"])
    if preview_img is not None:
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.location = (-100, -260)
        tex.label = "EEVEE preview (diffuse)"
        tex.image = preview_img
        tex.interpolation = 'Closest'
        tex.extension = 'REPEAT'
        nt.links.new(uv, tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], axf.inputs["Preview Diffuse"])
    return mat


def import_svbrdf(path: str, *, archive_source: bool = True) -> bpy.types.Material:
    m = read_svbrdf(path)
    atlas = build_svbrdf_atlas(m)
    base = m["name"] or os.path.splitext(os.path.basename(path))[0]
    h = atlas.shape[0] - 1
    w = atlas.shape[1] // 4
    with tempfile.TemporaryDirectory(prefix="mixar_axf_") as tmp:
        atlas_img = _packed_data_image(f"AxF {base} Atlas", atlas, tmp)
        preview_img = _preview_image(f"AxF {base} Preview", atlas[:h, :w, :3], tmp)

    mat = build_svbrdf_material(m, atlas_img, preview_img, name=f"AxF {base}")
    mat[C.PROP_SOURCE_NAME] = os.path.basename(path)
    mat[C.PROP_SOURCE_SHA256] = sha256_file(path)
    mat["axf_model"] = json.dumps({
        "representation": SVBRDF, "model": m["model"], "spec_type": m["spec_type"],
        "fresnel_f0": m["fresnel_f0"], "size_mm": list(m["size_mm"]), "origin": m["origin"],
        "map_size": [int(w), int(h)], "color_space": m["color_space"],
    })
    if archive_source:
        mat[C.PROP_ARCHIVE] = _archive_source(path, os.path.basename(path))
    if m["extra_materials"]:
        logger.warning("[AxF] %s holds %d more materials; imported the first (%s)",
                       os.path.basename(path), len(m["extra_materials"]), m["name"])
    logger.info("[AxF] imported %s as %s (SVBRDF)", os.path.basename(path), mat.name)
    return mat


def import_axf(path: str, *, archive_source: bool = True,
               fit_to_device: bool = False) -> bpy.types.Material:
    """Import an AxF car paint (CarPaint2) or SVBRDF material; other kinds are refused.

    Car paints with device readings in the file are compared with them (the material
    keeps the result as PROP_DEVICE_CHECK). fit_to_device: render refit lobes when the
    refit generalises (core/device_fit.py); the packed original stays the file."""
    if representation_class(path) == SVBRDF:
        return import_svbrdf(path, archive_source=archive_source)
    m = read_cpa2(path, load_flakes=True)
    file_lobes = m["lobes"]
    base = m["name"] or os.path.splitext(os.path.basename(path))[0]
    # The device check, the refit, the EEVEE fit and the source hash never touch bpy
    # (the fits only read m); they run on worker threads while this thread packs the
    # images and the original file. The EEVEE fit needs the refit's lobes, so with
    # fit_to_device it starts once the refit is in.
    archive = None
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="axf_fit") as pool, \
            tempfile.TemporaryDirectory(prefix="mixar_axf_") as tmp:
        device_future = pool.submit(device_fit.analyse, m, path, fit_to_device)
        sha_future = pool.submit(sha256_file, path)
        fit_future = None if fit_to_device else pool.submit(eevee_fit.fit, m)
        try:
            payload = build_payload(m)
            flakes_img = coat_img = None
            if payload["flake_atlas"] is not None:
                flakes_img = _packed_data_image(f"AxF {base} Flakes", payload["flake_atlas"], tmp)
            if payload["coat_normal_image"] is not None:
                coat_img = _packed_data_image(f"AxF {base} Coat Normal", payload["coat_normal_image"], tmp)
            if archive_source:
                archive = _archive_source(path, os.path.basename(path))
            device = device_future.result()
            if device is not None and device["fit"]["accepted"]:
                # Only the lobe texels of the table image change; flakes and coat do not.
                m = {**m, "lobes": np.asarray(device["fit"]["lobes"], np.float64)}
                payload["table_image"] = build_table_image_like(m, payload)
            if fit_future is None:
                fit_future = pool.submit(eevee_fit.fit, m)
            table_img = _packed_data_image(f"AxF {base} Table", payload["table_image"], tmp)
            fit_img = _packed_data_image(f"AxF {base} EEVEE Fit", fit_future.result(), tmp)
            source_sha = sha_future.result()
        except Exception:
            if archive is not None:
                bpy.data.images.remove(archive)
            raise

    mat = build_material(m, table_img, flakes_img, name=f"AxF {base}", coat_img=coat_img,
                         fit_img=fit_img)
    mat[C.PROP_SOURCE_NAME] = os.path.basename(path)
    mat[C.PROP_SOURCE_SHA256] = source_sha
    refit = device is not None and device["fit"]["accepted"]
    mat["axf_model"] = json.dumps({
        "representation": "CarPaint2", "kd": m["kd"], "lobes": file_lobes.tolist(),
        "render_lobes": m["lobes"].tolist(),
        "ior": m["ior"], "refractive": m["refractive"], "num_theta_f": m["num_theta_f"],
        "num_theta_i": m["num_theta_i"], "lut": m["lut"].tolist(), "patch_mm": list(m["patch_mm"]),
        "table_space": m["table_space"], "coat_normal_mm": list(m["coat_normal_mm"]),
    })
    mat[C.PROP_LOBES] = C.LOBES_DEVICE_FIT if refit else C.LOBES_FILE
    if device is not None:
        mat[C.PROP_DEVICE_CHECK] = json.dumps(device)
    if archive is not None:
        mat[C.PROP_ARCHIVE] = archive
    if m["extra_materials"]:
        logger.warning("[AxF] %s holds %d more materials; imported the first (%s)",
                       os.path.basename(path), len(m["extra_materials"]), m["name"])
    if device is not None:
        fit = device["fit"]
        logger.info("[AxF] %s vs device: %.2f / %.2f dE00 (mean / max)%s", os.path.basename(path),
                    device["file"]["mean"], device["file"]["max"],
                    "" if not fit["requested"] else
                    f"; fit to device {'applied' if fit['accepted'] else 'not applied'}: "
                    f"held out {fit['held_out_mean']:.2f} / {fit['held_out_max']:.2f} ({fit['reason']})")
    logger.info("[AxF] imported %s as %s", os.path.basename(path), mat.name)
    return mat


def export_axf(material: bpy.types.Material, filepath: str) -> str:
    """Write the packed original AxF back out; returns its SHA-256."""
    archive = material.get(C.PROP_ARCHIVE)
    if archive is None or archive.packed_file is None:
        raise ValueError(
            "This material's original .axf is not in the file (imported with Keep Original "
            "File off, or removed with File > Clean Up > Remove Embedded AxF Originals); "
            "re-import the .axf to export it")
    data = bytes(archive.packed_file.data)
    with open(filepath, "wb") as f:
        f.write(data)
    digest = sha256_file(filepath)
    expected = material.get(C.PROP_SOURCE_SHA256)
    if expected and digest != expected:
        raise ValueError("Exported AxF does not match the imported file")
    return digest
