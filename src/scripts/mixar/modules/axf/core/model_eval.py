# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Point evaluation of the CarPaint2 BRDF in the file's own colour space (pure numpy).

The same maths as the Cycles closure (intern/cycles/kernel/closure/bsdf_axf_carpaint.h,
axf_carpaint_eval_cos) for a flat sample with the coat normal equal to the base normal,
evaluated on the stored colour table (31 spectral bands on Pantora 2026 files) instead
of its Rec.709 projection, so the result compares with the device's spectral readings
without any colour conversion. Flakes enter as their patch mean, which is what a 6 mm
aperture reading averages.
"""

from __future__ import annotations

import math

import numpy as np

from .approx_fit import _ct, _fresnel, _refract, _table_lookup
from .payload import complete_table


def _flake_spectral_means(m: dict) -> np.ndarray | None:
    """(patches, bands): each flake patch's mean, stored sRGB,E -> the table's space."""
    flakes = m.get("flakes")
    if flakes is None or not m["lut"].size:
        return None
    means = flakes.reshape(flakes.shape[0], -1, 3).mean(axis=1).astype(np.float64)
    if m["table_space"] != "spectral":
        return means  # RGB files: the table and flakes are both sRGB,E
    to_spec = np.stack([np.interp(m["wavelengths"], m["to_spectral_wl"], m["to_spectral"][k])
                        for k in range(3)])
    return means @ m["rgb_e_to_xyz"] @ to_spec


def _flake_mean(m: dict, patch_means, thH: float, thD: float) -> np.ndarray:
    """The kernel's bilinear flake lookup (bins at k * (pi/2) / NumThetaF), on means."""
    lut = m["lut"]
    n = float(m["num_theta_f"])
    bh, bd = n * thH * (2 / math.pi), n * thD * (2 / math.pi)
    h0, d0 = int(math.floor(bh)), int(math.floor(bd))
    wh, wd = bh - h0, bd - d0
    rows, cols = lut.shape
    zero = np.zeros(patch_means.shape[1])

    def corner(hi, di):
        if di < 0 or di >= rows or hi < 0 or hi >= cols:
            return zero
        p = int(lut[di, hi])
        return patch_means[p] if p >= 0 else zero

    return ((1 - wd) * ((1 - wh) * corner(h0, d0) + wh * corner(h0 + 1, d0))
            + wd * ((1 - wh) * corner(h0, d0 + 1) + wh * corner(h0 + 1, d0 + 1)))


def prepare(m: dict) -> dict:
    """Per-material data reused across evaluations."""
    return {"table": complete_table(np.asarray(m["table"], np.float64)),
            "flake_means": _flake_spectral_means(m)}


def eval_cos(m: dict, prep: dict, light, view, *, lobes=None, kd=None,
             flake_strength: float = 1.0) -> np.ndarray:
    """f(light, view) * cos(theta_light) in the table's colour space (bands or RGB).

    light, view: unit vectors, normal +z. lobes / kd override the file's values (refit)."""
    light = np.asarray(light, np.float64)
    view = np.asarray(view, np.float64)
    if light[2] <= 0 or view[2] <= 0:
        return np.zeros(prep["table"].shape[-1])
    lobes = m["lobes"] if lobes is None else lobes
    kd = m["kd"] if kd is None else kd
    ior = m["ior"]
    if m["refractive"]:
        l = _refract(light, 1.0 / ior)
        v = _refract(view, 1.0 / ior)
    else:
        l, v = light, view
    h = l + v
    h = h / np.linalg.norm(h)
    nh, nl, nv = float(h[2]), float(l[2]), float(v[2])
    vh = min(max(float(h @ v), 1e-6), 1.0)
    thH = math.atan2(float(np.linalg.norm(np.cross([0.0, 0.0, 1.0], h))), max(nh, 0.0))
    thD = math.atan2(float(np.linalg.norm(np.cross(h, v))), vh)
    ct = float(_ct({"lobes": lobes}, np.array(nh), nv, nl, np.array(vh)))
    T = _table_lookup(prep["table"], np.array(thD), np.array(thH), m.get("table_texel_offset", 0.0))
    t = (1 - _fresnel(light[2], ior)) * (1 - _fresnel(view[2], ior))
    out = T * (kd / math.pi + ct) * (t * light[2])
    if prep["flake_means"] is not None and flake_strength:
        out = out + flake_strength * _flake_mean(m, prep["flake_means"], thH, thD)
    return np.asarray(out, np.float64)
