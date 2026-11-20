# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compare an AxF car paint's model with the device readings stored in its file.

One convention for every figure (tests, the import report, ACCURACY.md):
- device: the scans' spectral readings, averaged over scans per geometry;
- model: the CarPaint2 BRDF evaluated at the reading's emitter and pickup directions
  (core/model_eval.py, flakes as their patch mean);
- both sides as reflectance factor R = pi * f (the stored f * cos(theta_emitter)
  divided by that cosine);
- colour: CIE 1931 2 degree observer, D65, Lab against the perfect white, CIEDE2000
  (core/colorimetry.py).

The model is linear in the per-geometry scalar s = kd / pi + CT(lobes), so each
geometry is precomputed as XYZ = s * XYZ_base + XYZ_flakes; the lobe refit
(core/device_fit.py) evaluates thousands of candidates with that.
"""

from __future__ import annotations

import math

import numpy as np

from . import colorimetry as cm
from . import model_eval
from .approx_fit import _fresnel, _refract, _table_lookup
from .device_readings import geometry_order, mean_readings


def prepare(m: dict, readings: dict) -> dict | None:
    """Per-geometry data for fast evaluation, or None when the file has no readings or
    its colour table is not spectral (the readings are spectral)."""
    if not readings["scans"] or m["table_space"] != "spectral":
        return None
    wl = readings["wavelengths"]
    if len(wl) != np.asarray(m["table"]).shape[-1] or not np.allclose(wl, m["wavelengths"]):
        return None
    mean = mean_readings(readings)
    names = geometry_order(mean)
    prep = model_eval.prepare(m)
    ior = m["ior"]
    rows = {k: [] for k in ("base", "flake", "dev_xyz", "nh", "nl", "nv", "vh")}
    for name in names:
        g = mean[name]
        light, view = g["emitter"], g["pickup"]
        l, v = (_refract(light, 1 / ior), _refract(view, 1 / ior)) if m["refractive"] else (light, view)
        h = (l + v) / np.linalg.norm(l + v)
        nh, nl, nv = float(h[2]), float(l[2]), float(v[2])
        vh = min(max(float(h @ v), 1e-6), 1.0)
        thH = math.atan2(float(np.hypot(h[0], h[1])), max(nh, 0.0))
        thD = math.atan2(float(np.linalg.norm(np.cross(h, v))), vh)
        T = _table_lookup(prep["table"], np.array(thD), np.array(thH), m.get("table_texel_offset", 0.0))
        t = (1 - _fresnel(light[2], ior)) * (1 - _fresnel(view[2], ior))
        to_r = math.pi / light[2]  # f * cos(theta_emitter) -> reflectance factor
        rows["base"].append(cm.spectrum_to_xyz(T * t * light[2] * to_r, wl))
        flake = np.zeros(3)
        if prep["flake_means"] is not None:
            flake = cm.spectrum_to_xyz(model_eval._flake_mean(m, prep["flake_means"], thH, thD) * to_r, wl)
        rows["flake"].append(flake)
        rows["dev_xyz"].append(cm.spectrum_to_xyz(g["value"] * to_r, wl))
        for k, val in (("nh", nh), ("nl", nl), ("nv", nv), ("vh", vh)):
            rows[k].append(val)
    out = {k: np.asarray(v, np.float64) for k, v in rows.items()}
    out["white"] = cm.white_xyz(wl)
    out["dev"] = cm.xyz_to_lab(out["dev_xyz"], out["white"])
    out.update({"names": names, "kd": float(m["kd"]),
                "lobes": np.asarray(m["lobes"], np.float64),
                "scans": [mean[n]["scans"] for n in names]})
    out["repeatability"] = _repeatability(readings, names, wl)
    return out


def _repeatability(readings: dict, names, wl) -> np.ndarray:
    """Per geometry: the largest CIEDE2000 between any two scans (NaN with one scan)."""
    rep = np.full(len(names), np.nan)
    scans = readings["scans"]
    for i, name in enumerate(names):
        labs = [cm.spectrum_to_lab(s["geometries"][name]["value"] * math.pi / s["geometries"][name]["emitter"][2], wl)
                for s in scans if name in s["geometries"]]
        if len(labs) > 1:
            rep[i] = max(float(cm.ciede2000(a, b)) for j, a in enumerate(labs) for b in labs[j + 1:])
    return rep


def ct_scalar(d: dict, lobes) -> np.ndarray:
    """X-Rite's multi-lobe Cook-Torrance at each prepared geometry (no colour)."""
    nh = np.clip(d["nh"], 1e-6, 1)
    cos2 = nh * nh
    vh, nv, nl = d["vh"], d["nv"], d["nl"]
    G = np.minimum(1, np.minimum(2 * nh * nv / vh, 2 * nh * nl / vh))
    s = np.zeros_like(nh)
    for c, mm, f0 in lobes:
        if c <= 0:
            continue
        m2 = mm * mm
        D = np.exp((cos2 - 1) / (cos2 * m2)) / (m2 * cos2 * cos2)
        s = s + c * D * (f0 + (1 - f0) * (1 - vh) ** 5)
    return s * G / (math.pi * np.maximum(nv * nl, 1e-12))


def model_xyz(d: dict, lobes=None, kd=None) -> np.ndarray:
    lobes = d["lobes"] if lobes is None else lobes
    kd = d["kd"] if kd is None else kd
    s = kd / math.pi + ct_scalar(d, lobes)
    return s[:, None] * d["base"] + d["flake"]


def model_lab(d: dict, lobes=None, kd=None) -> np.ndarray:
    return cm.xyz_to_lab(model_xyz(d, lobes, kd), d["white"])


def delta_e(d: dict, lobes=None, kd=None) -> np.ndarray:
    return cm.ciede2000(d["dev"], model_lab(d, lobes, kd))


def report(d: dict, lobes=None, kd=None) -> dict:
    """Per-geometry rows and the summary every surface shows."""
    xyz = model_xyz(d, lobes, kd)
    lab = cm.xyz_to_lab(xyz, d["white"])
    de = cm.ciede2000(d["dev"], lab)
    share = cm.lightness_share(d["dev"], lab)
    y_ratio = xyz[:, 1] / np.maximum(d["dev_xyz"][:, 1], 1e-12)
    rows = [{"geometry": n, "de2000": float(e), "lightness_share": float(ls),
             "y_ratio": float(yr), "scans": int(sc),
             "repeatability": None if math.isnan(r) else float(r)}
            for n, e, ls, yr, sc, r in zip(d["names"], de, share, y_ratio, d["scans"], d["repeatability"])]
    return {"mean": float(np.mean(de)), "max": float(np.max(de)),
            "worst": d["names"][int(np.argmax(de))], "rows": rows,
            "convention": f"CIEDE2000, {cm.ILLUMINANT}, {cm.OBSERVER}, reflectance factor, scan mean"}
