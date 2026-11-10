# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Per-view-angle fit of an AxF CarPaint2 BRDF to the closures EEVEE draws (pure numpy).

EEVEE lights a closure with its own lobe shapes: Lambert for diffuse and a GGX lobe
normalised to unit albedo (its colour is the directional albedo). A material shader
cannot see the light direction, so the AxF node's EEVEE path picks, per view angle:

  Cd(view):     the exact diffuse-part albedo (colour table x kd, both coat passes),
  Cs(view):     the exact Cook-Torrance albedo (colour table x lobes, both coat passes),
  r(view):      the GGX roughness whose lobe best matches the exact lobe, scored on
                cube-root radiance (close to how CIELAB weighs it) over every light
                direction, with the diffuse part included so tails count as they show,
  g_f(view):    the gain that makes a flake BTF value b seen at the mirror direction
                render as radiance b (BTF = radiance per unit normal irradiance),

each divided by the view-side coat transmission the node applies. The result is a
64 x 2 RGBA float image the node reads with the view angle (texel k at (k + 0.5) / 64
of [0, pi/2]): row 0 = (Cd, r), row 1 = (Cs, g_f).
"""

from __future__ import annotations

import math

import numpy as np

from .approx_fit import N_VIEW, _ct, _fresnel, _refract, _table_lookup
from .payload import table_rgb709

_HEMI = (120, 240)


def _hemisphere(n_t, n_p):
    t = (np.arange(n_t) + 0.5) / n_t * (math.pi / 2)
    p = (np.arange(n_p) + 0.5) / n_p * (2 * math.pi)
    T, P = np.meshgrid(t, p, indexing="ij")
    w = np.stack([np.sin(T) * np.cos(P), np.sin(T) * np.sin(P), np.cos(T)], -1)
    dw = np.sin(T) * (math.pi / 2 / n_t) * (2 * math.pi / n_p)
    return w, dw


def _ggx_geometry(wo, wi):
    """The roughness-independent parts of the GGX reflection BRDF (Smith G, no Fresnel)
    for view wo and light directions wi: computed once per view, since the roughness
    search evaluates the lobe dozens of times."""
    h = wi + wo
    h = h / np.maximum(np.linalg.norm(h, axis=-1, keepdims=True), 1e-12)
    c = np.clip(h[..., 2], 0, 1)
    ci = np.clip(wi[..., 2], 1e-6, 1)
    co = min(max(float(wo[2]), 1e-6), 1.0)
    return c * c, ci, 1 - ci * ci, ci * ci, co, 1 - co * co, co * co


def _ggx_fast(alpha, geo):
    """GGX reflection BRDF at alpha for the directions _ggx_geometry was given."""
    c2, ci, si2, ci2, co, so2, co2 = geo
    a2 = alpha * alpha
    D = a2 / (math.pi * (c2 * (a2 - 1) + 1) ** 2)
    gi = 2 / (1 + np.sqrt(1 + a2 * si2 / ci2))
    go = 2 / (1 + math.sqrt(1 + a2 * so2 / co2))
    return D * gi * go / (4 * ci * co)


def _lobe(r, geo, mirror_geo, cos_i, dw):
    """EEVEE's GGX lobe at roughness r per unit albedo, times the light cosine, and its
    value toward the mirror direction (times the view cosine)."""
    f = _ggx_fast(r * r, geo)
    alb = max(float(np.sum(f * cos_i * dw)), 1e-12)
    return f * cos_i / alb, float(_ggx_fast(r * r, mirror_geo)[0]) * mirror_geo[4] / alb


def fit(m: dict) -> np.ndarray:
    """The 2 x N_VIEW x 4 float32 LUT rows (row 0 first) for material m (read_cpa2)."""
    wi, dw = _hemisphere(*_HEMI)
    views = (np.arange(N_VIEW) + 0.5) / N_VIEW * (math.pi / 2)
    ior = m["ior"]
    eta = 1.0 / ior if m["refractive"] else 1.0
    table = table_rgb709(m)
    wi_r = _refract(wi, eta) if m["refractive"] else wi
    t_i = 1 - _fresnel(wi[..., 2], ior)
    cos_i = wi[..., 2]
    lum_w = np.array([0.2126, 0.7152, 0.0722])

    lut = np.zeros((2, N_VIEW, 4), np.float32)
    for k, th in enumerate(views):
        wo = np.array([math.sin(th), 0.0, math.cos(th)])
        wo_r = _refract(wo, eta) if m["refractive"] else wo
        t_o = 1 - _fresnel(wo[2], ior)
        h = wi_r + wo_r
        h /= np.linalg.norm(h, axis=-1, keepdims=True)
        nh, nl, nv = h[..., 2], wi_r[..., 2], wo_r[2]
        vh = np.clip(np.sum(h * wo_r, -1), 1e-6, 1)
        thH = np.arccos(np.clip(nh, 0, 1))
        thD = np.arccos(vh)
        T = _table_lookup(table, thD, thH, m.get("table_texel_offset", 0.0))
        tt = (t_i * t_o)[..., None]
        # Radiance per unit normal irradiance, times the light cosine, per light direction.
        diff = T * (m["kd"] / math.pi) * tt * cos_i[..., None]
        spec = T * _ct(m, nh, nv, nl, vh)[..., None] * tt * cos_i[..., None]
        Cd = np.sum(diff * dw[..., None], axis=(0, 1))
        Cs = np.sum(spec * dw[..., None], axis=(0, 1))
        # Choose the roughness on luminance: Lambert diffuse plus the normalised GGX lobe.
        d_lum = float(Cd @ lum_w) * cos_i / math.pi
        s_lum = float(Cs @ lum_w)
        target = np.cbrt(np.maximum((diff + spec) @ lum_w, 0))

        geo = _ggx_geometry(wo, wi)
        mirror_geo = _ggx_geometry(wo, np.array([[-wo[0], 0.0, wo[2]]]))

        def score(r):
            lobe, peak = _lobe(r, geo, mirror_geo, cos_i, dw)
            model = np.cbrt(np.maximum(d_lum + s_lum * lobe, 0))
            return float(np.sum((model - target) ** 2 * dw)), peak

        # Coarse grid, then refinements around the best (the score is smooth in r).
        grid = np.linspace(0.06, 1.0, 17)
        for _ in range(3):
            scored = [score(x) for x in grid]
            best = int(np.argmin([s for s, _ in scored]))
            r, peak = float(grid[best]), scored[best][1]
            step = grid[1] - grid[0]
            grid = np.linspace(max(r - step, 0.02), min(r + step, 1.0), 9)
        lut[0, k, :3] = Cd / t_o
        lut[0, k, 3] = r
        lut[1, k, :3] = Cs / t_o
        # Flake BTF b at the mirror renders as b: colour = b / (lobe peak x t_o).
        lut[1, k, 3] = 1.0 / max(peak * t_o, 1e-12)
    return lut
