# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opt-in refit of a car paint's Cook-Torrance lobes to its own device readings.

Pantora 2026 files store three CarPaint2 lobes but only the first is active, which
leaves metallics too dark at the 22.5 degree half-angle and too bright at the flop.
This refits two lobes (coefficient and spread; F0 stays the file's) to the readings in
the file, keeping the colour table, diffuse kd, clear coat and flakes as stored. On the
eight scans_blr paints a third lobe never lowered the held-out error, a free kd was
mixed, and a free F0 reached the same error through degenerate lobes (F0 near 0 with a
large coefficient, a lobe that acts only through the Fresnel tail), so none of them is
fitted. The result is accepted only when it generalises:

- leave-one-geometry-out: every geometry is predicted by a fit that never saw it;
- accepted only if the held-out mean and the held-out maximum CIEDE2000 both improve
  on the file's model by at least MIN_GAIN;
- the refit lobes keep the directional albedo of the whole BRDF at or below 1.

A refit trades error between geometries: the 22.5 degree half-angle errors fall
(silver 8.8 -> 2.1 held out) while some near-specular geometries the file already
matched rise (by up to about 1.8). Every geometry whose held-out error rises by more
than its scan repeatability is listed in the result ("worse"), so the import report
can show the trade.

The packed original is never changed; export still writes the measured file.
Pure numpy (no SciPy in the embedded Python): a bounded Nelder-Mead.
"""

from __future__ import annotations

import math

import numpy as np

from . import device_check as dc

# Lobe width bounds. The files' own lobes sit at 0.10-0.14; below 0.05 a fold could fit a
# needle lobe on one near-specular geometry (21.9 dE00 held out on white at 0.02).
M_MIN, M_MAX = 0.05, 1.0
FIT_LOBES = 2
MIN_GAIN = 0.1           # held-out mean and max must improve by at least this (dE00)
DEFAULT_TOLERANCE = 0.3  # repeatability assumed where the file has one scan (dE00)

# Decision codes (the UI words them: ui/panels/axf_material_panel.py).
REASON_ACCEPTED = "accepted"
REASON_MEAN = "held_out_mean"
REASON_MAX = "held_out_max"
REASON_ALBEDO = "albedo"


def _decode(x: np.ndarray, n: int, f0: float) -> np.ndarray:
    """Unbounded (c, m) per lobe -> lobes (c > 0, M_MIN <= m <= M_MAX, shared F0)."""
    x = x.reshape(n, 2)
    c = np.exp(np.clip(x[:, 0], -50, 50))
    m = M_MIN + (M_MAX - M_MIN) / (1 + np.exp(-np.clip(x[:, 1], -50, 50)))
    return np.stack([c, m, np.full(n, f0)], 1)


def _encode(lobes: np.ndarray) -> np.ndarray:
    lobes = np.asarray(lobes, np.float64)
    c = np.log(np.maximum(lobes[:, 0], 1e-9))
    mm = np.clip((lobes[:, 1] - M_MIN) / (M_MAX - M_MIN), 1e-4, 1 - 1e-4)
    return np.stack([c, np.log(mm / (1 - mm))], 1).ravel()


def _nelder_mead(f, x0, step=0.5, iters=1500, tol=1e-7):
    n = len(x0)
    pts = [np.asarray(x0, np.float64)] + [x0 + step * np.eye(n)[i] for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = np.argsort(vals)
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) < tol:
            break
        cen = np.mean(pts[:-1], axis=0)
        xr = cen + (cen - pts[-1]); fr = f(xr)
        if fr < vals[0]:
            xe = cen + 2 * (cen - pts[-1]); fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = cen + 0.5 * (pts[-1] - cen); fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = int(np.argmin(vals))
    return pts[i], vals[i]


def _file_f0(file_lobes: np.ndarray) -> float:
    """The F0 of the file's strongest lobe (shared by the refit lobes)."""
    return float(file_lobes[int(np.argmax(file_lobes[:, 0])), 2])


def _starts(file_lobes: np.ndarray, n: int) -> list:
    """Initial lobe sets: the file's active lobe first, extra lobes wider and weaker."""
    active = file_lobes[file_lobes[:, 0] > 0]
    first = active[0] if len(active) else np.array([0.05, 0.15, 0.5])
    starts = []
    for widths in ((0.3, 0.6), (0.08, 0.3), (0.2, 0.45)):
        lobes = [first]
        for k in range(n - 1):
            lobes.append([first[0] * 0.2, widths[k % 2], 0.2])
        starts.append(np.asarray(lobes, np.float64))
    return starts


def _fit(d: dict, n: int, mask: np.ndarray, starts, f0: float, step: float = 0.5) -> np.ndarray:
    """Lobes minimising the mean squared dE00 over the masked geometries."""

    def objective(x):
        de = dc.delta_e(d, _decode(x, n, f0))[mask]
        return float(np.mean(de * de))

    best = None
    for s in starts:
        x, v = _nelder_mead(objective, _encode(s), step=step)
        x, v = _nelder_mead(objective, x, step=min(0.1, step / 2))  # restart: Nelder-Mead stalls
        if best is None or v < best[1]:
            best = (x, v)
    return _decode(best[0], n, f0)


def _albedo_ok(m: dict, lobes: np.ndarray) -> bool:
    """Directional albedo of diffuse + lobes (coat transmission included) <= 1."""
    from .approx_fit import _ct, _fresnel, _hemisphere, _refract
    wi, dw = _hemisphere(90, 180)
    eta = 1 / m["ior"] if m["refractive"] else 1.0
    wi_r = _refract(wi, eta) if m["refractive"] else wi
    t_i = 1 - _fresnel(wi[..., 2], m["ior"])
    for th in np.radians([5, 30, 50, 70, 85]):
        wo = np.array([math.sin(th), 0.0, math.cos(th)])
        wo_r = _refract(wo, eta) if m["refractive"] else wo
        h = wi_r + wo_r
        h /= np.linalg.norm(h, axis=-1, keepdims=True)
        vh = np.clip(np.sum(h * wo_r, -1), 1e-6, 1)
        f = m["kd"] / math.pi + _ct({"lobes": lobes}, h[..., 2], wo_r[2], wi_r[..., 2], vh)
        t = t_i * (1 - _fresnel(wo[2], m["ior"]))
        # The colour table peaks near 1 on bright paints; bound the colourless part.
        if float(np.sum(f * t * wi[..., 2] * dw)) > 1.0:
            return False
    return True


def refit(m: dict, d: dict, n_lobes: int = FIT_LOBES) -> dict:
    """Refit n_lobes lobes; return the decision and every figure behind it.

    d: device_check.prepare(m, readings). Result keys: accepted, lobes (the lobes to
    render: refit, or the file's when not accepted), file (report), refit (report of
    the full fit, or None), held_out (per-geometry leave-one-out dE00), held_out_mean,
    held_out_max, worse (geometries whose held-out error rises past repeatability),
    reason."""
    base = dc.report(d)
    base_de = np.array([r["de2000"] for r in base["rows"]])
    tol = np.where(np.isnan(d["repeatability"]), DEFAULT_TOLERANCE,
                   np.maximum(d["repeatability"], DEFAULT_TOLERANCE))
    n_geo = len(d["names"])
    f0 = _file_f0(d["lobes"])
    full = _fit(d, n_lobes, np.ones(n_geo, bool), _starts(d["lobes"], n_lobes), f0)
    # Each fold starts from the full fit: on the scans_blr paints this matches cold
    # multi-start folds to 0.001 dE00 at a third of the cost.
    loo = np.zeros(n_geo)
    for i in range(n_geo):
        mask = np.ones(n_geo, bool)
        mask[i] = False
        lobes_i = _fit(d, n_lobes, mask, [full], f0, step=0.1)
        loo[i] = dc.delta_e(d, lobes_i)[i]
    out = {"file": base, "held_out": [float(v) for v in loo],
           "held_out_mean": float(loo.mean()), "held_out_max": float(loo.max()),
           "worse": [n for n, a, b, t in zip(d["names"], loo, base_de, tol) if a > b + t],
           "lobes": np.asarray(m["lobes"], np.float64), "accepted": False, "refit": None}
    if not loo.mean() <= base["mean"] - MIN_GAIN:
        out["reason"] = REASON_MEAN
        return out
    if not loo.max() <= base["max"] - MIN_GAIN:
        out["reason"] = REASON_MAX
        return out
    lobes = full
    if not _albedo_ok(m, lobes):
        out["reason"] = REASON_ALBEDO
        return out
    padded = np.zeros((max(len(m["lobes"]), len(lobes)), 3))
    padded[:, 1:] = (0.35, 0.04)  # the file's own placeholder for unused lobes
    padded[:len(lobes)] = lobes
    out.update({"accepted": True, "lobes": padded, "refit": dc.report(d, padded),
                "reason": REASON_ACCEPTED})
    return out


def analyse(m: dict, path: str, fit_to_device: bool) -> dict | None:
    """The device check (and, when asked, the refit) for an imported car paint, as
    the JSON-ready summary the material keeps. None when the file has no spectral
    device readings. Pure: safe on a worker thread."""
    from .device_readings import read_device_readings

    d = dc.prepare(m, read_device_readings(path))
    if d is None:
        return None
    file_report = dc.report(d)
    summary = {"convention": file_report["convention"], "file": file_report,
               "fit": {"requested": bool(fit_to_device), "accepted": False}}
    if fit_to_device:
        res = refit(m, d)
        summary["fit"].update({
            "accepted": res["accepted"], "reason": res["reason"],
            "held_out_mean": res["held_out_mean"], "held_out_max": res["held_out_max"],
            "held_out": res["held_out"], "worse": res["worse"],
            "refit": res["refit"], "lobes": np.asarray(res["lobes"]).tolist(),
        })
    return summary
