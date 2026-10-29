# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Build the two images the native AxF Car Paint BSDF reads (pure numpy).

Table image (float32 RGBA, width = thetaH bins):
  row 0..: parameter texel stream (see bsdf_axf_carpaint.h)
  row table_row0..: colour table in linear Rec.709 under a D65 (white) light,
                    row = thetaD bin, column = thetaH bin.
Flakes image (float32 RGBA): the AxF flake patches, values exactly as stored
(sRGB primaries, E white), tiled ATLAS_COLUMNS wide; image row = patch row in
file order. The parameters carry the 3x3 matrix to Rec.709.
Coat normal image (float32 RGBA): the clear coat normal map exactly as stored,
row = map row (V), column = map column (U).

Arrays are returned in image-memory order (row 0 = first row Cycles reads);
write them with exr_rows_for_blender() so Blender's bottom-up pixels match.
"""

from __future__ import annotations

import math

import numpy as np

from .. import constants as C


def spectral_to_rec709_matrix(wavelengths) -> np.ndarray:
    """(bands, 3) matrix: reflectance spectrum under D65 -> linear Rec.709, white = 1."""
    wl = np.asarray(wavelengths, np.float64)
    ref = np.asarray(C.WAVELENGTHS, np.float64)
    if wl.shape != ref.shape or not np.allclose(wl, ref):
        cmf = np.stack([np.interp(wl, ref, C.CMF_X), np.interp(wl, ref, C.CMF_Y),
                        np.interp(wl, ref, C.CMF_Z)], axis=1)
        s = np.interp(wl, ref, C.D65)
    else:
        cmf = np.stack([C.CMF_X, C.CMF_Y, C.CMF_Z], axis=1).astype(np.float64)
        s = np.asarray(C.D65, np.float64)
    w = (s[:, None] * cmf) / np.sum(s * cmf[:, 1])
    m = w @ np.asarray(C.XYZ_TO_REC709, np.float64).T
    # The 400-700 nm window moves the D65 white point by up to 0.3 %; normalise so a
    # perfectly white reflector under a white light renders exactly white.
    return m / m.sum(axis=0, keepdims=True)


def complete_table(table: np.ndarray) -> np.ndarray:
    """Fill a colour table that is only defined on the triangle thetaD + thetaH <= E.

    X-Rite's 2016 encoder left the rest zero (unreachable black at grazing angles); its
    2026 encoder writes the same triangle and fills the rest by clamping thetaD onto
    the triangle's edge: T[d, h] = T[min(d, E - min(h, E)), min(h, E)] (verified texel
    for texel on a 2026 file). Tables of any other shape are returned unchanged."""
    nd, nh = table.shape[:2]
    if nd != nh:
        return table
    d, h = np.meshgrid(np.arange(nd), np.arange(nh), indexing="ij")
    defined = np.any(table != 0, axis=-1)
    if defined.all() or not defined.any():
        return table
    e = int((d + h)[defined].max())
    if not np.array_equal(defined, d + h <= e):
        return table
    hc = np.minimum(h, e)
    return table[np.minimum(d, e - hc), hc]


def table_rgb709(m: dict) -> np.ndarray:
    """The colour table [thetaD, thetaH, 3] in linear Rec.709.

    A spectral table is integrated under D65 (white = white). An RGB table is stored
    in linear sRGB primaries with an E white; it is used as is, which is what X-Rite's
    SDK hands every renderer (Unreal, MDL) that asks it for linear sRGB."""
    table = complete_table(np.asarray(m["table"], np.float64))
    if m["table_space"] == "spectral":
        return table @ spectral_to_rec709_matrix(m["wavelengths"])
    return table


def flake_rgb_matrix(m: dict) -> np.ndarray:
    """3x3 (row-major, applied as M @ rgb): stored flake RGB -> Rec.709 under D65.

    Spectral files: stored RGB (sRGB primaries, E white) -> XYZ with the file's own
    matrix, XYZ -> spectrum with the file's ToSpectralMatrix (an XYZ->spectral basis),
    then the same spectral -> Rec.709 projection as the colour table. RGB files: the
    identity, as for their colour table."""
    if m["table_space"] != "spectral":
        return np.eye(3)
    to_spec = np.stack([np.interp(m["wavelengths"], m["to_spectral_wl"], m["to_spectral"][k])
                        for k in range(3)])                        # (3, bands): xyz -> spectrum
    s2rgb = spectral_to_rec709_matrix(m["wavelengths"])           # (bands, 3)
    row_major = m["rgb_e_to_xyz"] @ to_spec @ s2rgb               # rgb(row) -> 709(row)
    return row_major.T


def build_table_image(m: dict, atlas_columns: int, patch_shape, atlas_shape=(0, 0)) -> tuple[np.ndarray, dict]:
    rgb = table_rgb709(m)                                          # [thetaD, thetaH, 3]
    nd, nh, _ = rgb.shape

    lobes = np.asarray(m["lobes"], np.float64)
    lut = np.asarray(m["lut"], np.int64)
    lut_rows, lut_cols = (lut.shape if lut.size else (0, 0))
    patch_h, patch_w = patch_shape
    fm = flake_rgb_matrix(m)

    stream = [
        (C.PARAM_VERSION, m["kd"], m["ior"], 1.0 if m["refractive"] else 0.0),
        (len(lobes), m["num_theta_f"], lut_rows, lut_cols),
        (atlas_columns, patch_w, patch_h, nd),
        (0.0, 0.0, 0.0, 0.0),  # (table_row0, atlas_w, atlas_h), filled below
        (fm[0, 0], fm[0, 1], fm[0, 2], 0.0),
        (fm[1, 0], fm[1, 1], fm[1, 2], 0.0),
        (fm[2, 0], fm[2, 1], fm[2, 2], 0.0),
    ]
    stream += [(c, mm, f0, 0.0) for c, mm, f0 in lobes]
    flat = list(lut.ravel())
    flat += [-1] * ((-len(flat)) % 4)
    stream += [tuple(flat[i:i + 4]) for i in range(0, len(flat), 4)]
    table_row0 = math.ceil(len(stream) / nh)
    stream[3] = (float(table_row0), float(atlas_shape[1]), float(atlas_shape[0]), 0.0)

    image = np.zeros((table_row0 + nd, nh, 4), np.float32)
    params = np.zeros((table_row0 * nh, 4), np.float32)
    params[:len(stream)] = np.asarray(stream, np.float64)
    image[:table_row0] = params.reshape(table_row0, nh, 4)
    image[table_row0:, :, :3] = rgb
    image[table_row0:, :, 3] = 1.0
    info = {"table_row0": table_row0, "flake_matrix": fm, "table_rgb": rgb}
    return image, info


def build_flake_atlas(flakes: np.ndarray, atlas_columns: int) -> np.ndarray:
    n, h, w, _ = flakes.shape
    rows = math.ceil(n / atlas_columns)
    atlas = np.zeros((rows * h, atlas_columns * w, 4), np.float32)
    atlas[..., 3] = 1.0
    for i in range(n):
        r, c = divmod(i, atlas_columns)
        atlas[r * h:(r + 1) * h, c * w:(c + 1) * w, :3] = flakes[i]
    return atlas


def build_coat_normal_image(coat_normal: np.ndarray) -> np.ndarray:
    h, w, _ = coat_normal.shape
    image = np.ones((h, w, 4), np.float32)
    image[..., :3] = coat_normal
    return image


def build_payload(m: dict, atlas_columns: int = C.ATLAS_COLUMNS) -> dict:
    flakes = m.get("flakes")
    patch_shape = flakes.shape[1:3] if flakes is not None else (0, 0)
    atlas = build_flake_atlas(flakes, atlas_columns) if flakes is not None else None
    table_image, info = build_table_image(m, atlas_columns if flakes is not None else 0, patch_shape,
                                          atlas.shape[:2] if atlas is not None else (0, 0))
    coat = m.get("coat_normal")
    coat_image = build_coat_normal_image(coat) if coat is not None else None
    return {"table_image": table_image, "flake_atlas": atlas, "coat_normal_image": coat_image, **info}


def preview_inputs(m: dict) -> dict:
    """EEVEE preview values derived from the same data (normal incidence)."""
    rgb = table_rgb709(m)[0, 0]
    lobes = np.asarray(m["lobes"], np.float64)
    k = int(np.argmax(lobes[:, 0])) if len(lobes) else 0
    c, spread, f0 = lobes[k] if len(lobes) else (0.0, 0.3, 0.04)
    # Diffuse albedo kd * T; Beckmann spread m ~ GGX alpha = roughness^2.
    diffuse = np.clip(m["kd"] * rgb, 0.0, 1.0)
    # Hemispherical albedo of X-Rite's CT lobe ~ 4 c F0 (their D has no 1/pi; G ~ 1).
    specular = np.clip(4.0 * c * f0 * rgb, 0.0, 1.0)
    roughness = float(np.clip(math.sqrt(max(spread, 0.0)), 0.0, 1.0))
    return {"diffuse": tuple(diffuse), "specular": tuple(specular), "roughness": roughness,
            "coat_ior": float(m["ior"])}
