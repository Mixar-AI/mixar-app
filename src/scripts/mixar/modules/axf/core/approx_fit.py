# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Fit a stock-Blender node approximation of an AxF CarPaint2 BRDF (pure numpy).

Stock shader nodes cannot see the light direction, so the exact model cannot be
expressed with them. This fits, per VIEW angle, the closures stock nodes can
make so they reproduce the exact BRDF where it matters:

  surface = Mix(Fresnel_coat(view),
                Diffuse(Cd) + Glossy_Beckmann(Cs, a_s) + Glossy_Beckmann(flake_rgb * g_f, a_s),
                Glossy(sharp, white))

- Cd(view): the exact diffuse-part albedo (colour table x kd, both coat passes)
  divided by the view-side coat transmission the Mix node applies;
- Cs, a_s: the exact outer Cook-Torrance lobe's albedo and peak;
- flakes: the exact flake BTF slice at the mirror configuration (thetaH = 0),
  bilinear across thetaI bins, as a sparkle lobe whose mean is removed from Cs; the
  BTF is radiance per unit normal irradiance (no coat transmission, no cosine).
"""

from __future__ import annotations

import math

import numpy as np

from .payload import flake_rgb_matrix, table_rgb709

N_VIEW = 64


def _fresnel(c, ior):
    c = np.clip(c, 0.0, 1.0)
    st = np.sqrt(np.clip(1 - c * c, 0, None)) / ior
    ct = np.sqrt(np.clip(1 - st * st, 0, None))
    rs = (c - ior * ct) / (c + ior * ct)
    rp = (ct - ior * c) / (ct + ior * c)
    return 0.5 * (rs * rs + rp * rp)


def _refract(w, eta):
    c = w[..., 2]
    ct = np.sqrt(np.clip(1 - eta * eta * (1 - c * c), 0, None))
    out = np.stack([eta * w[..., 0], eta * w[..., 1], ct], -1)
    return out / np.linalg.norm(out, axis=-1, keepdims=True)


def _table_lookup(table, thD, thH):
    nd, nh = table.shape[:2]
    y = np.minimum(thD * (2 / math.pi) * nd, nd - 1)   # texel i at i / n (X-Rite's addressing)
    x = np.minimum(thH * (2 / math.pi) * nh, nh - 1)
    y0 = np.clip(np.floor(y), 0, nd - 1).astype(int); x0 = np.clip(np.floor(x), 0, nh - 1).astype(int)
    y1 = np.minimum(y0 + 1, nd - 1); x1 = np.minimum(x0 + 1, nh - 1)
    fy = np.where(y >= nd - 1, 0, np.clip(y - np.floor(y), 0, 1))[..., None]
    fx = np.where(x >= nh - 1, 0, np.clip(x - np.floor(x), 0, 1))[..., None]
    return ((1 - fy) * ((1 - fx) * table[y0, x0] + fx * table[y0, x1])
            + fy * ((1 - fx) * table[y1, x0] + fx * table[y1, x1]))


def _ct(m, nh, nv, nl, vh):
    nh = np.clip(nh, 1e-6, 1); cos2 = nh * nh
    G = np.minimum(1, np.minimum(2 * nh * nv / vh, 2 * nh * nl / vh))
    s = np.zeros_like(nh)
    for c, mm, f0 in m["lobes"]:
        if c <= 0:
            continue
        m2 = mm * mm
        D = np.exp((cos2 - 1) / (cos2 * m2)) / (m2 * cos2 * cos2)
        s = s + c * D * (f0 + (1 - f0) * (1 - vh) ** 5)
    return s * G / (math.pi * np.maximum(nv * nl, 1e-12))


def _blender_beckmann(alpha, cos_i, cos_o, cos_h):
    """Cycles' Beckmann glossy (Fresnel = colour) without the colour."""
    a2 = alpha * alpha
    c2 = np.clip(cos_h, 1e-6, 1) ** 2
    D = np.exp((c2 - 1) / (c2 * a2)) / (math.pi * a2 * c2 * c2)

    def lam(c):
        c = np.clip(c, 1e-6, 1)
        a = c / (alpha * np.sqrt(np.clip(1 - c * c, 1e-12, None)))
        return np.where(a < 1.6, (1 - 1.259 * a + 0.396 * a * a) / (3.535 * a + 2.181 * a * a), 0.0)

    G = 1 / (1 + lam(cos_i) + lam(cos_o))
    return D * G / (4 * np.clip(cos_i, 1e-6, None) * np.clip(cos_o, 1e-6, None))


def _hemisphere(n_t=360, n_p=720):
    t = (np.arange(n_t) + 0.5) / n_t * (math.pi / 2)
    p = (np.arange(n_p) + 0.5) / n_p * (2 * math.pi)
    T, P = np.meshgrid(t, p, indexing="ij")
    w = np.stack([np.sin(T) * np.cos(P), np.sin(T) * np.sin(P), np.cos(T)], -1)
    dw = np.sin(T) * (math.pi / 2 / n_t) * (2 * math.pi / n_p)
    return w, dw


def _unit_albedo(alpha, wo, wi, cos_i, dw):
    hb = wi + wo
    hb = hb / np.linalg.norm(hb, axis=-1, keepdims=True)
    fb = _blender_beckmann(alpha, cos_i, wo[2], hb[..., 2])
    return fb, float(np.sum(fb * cos_i * dw))


def fit(m: dict) -> dict:
    ior = m["ior"] if m["refractive"] else 1.0
    eta = 1.0 / ior
    table = table_rgb709(m)                                    # [thetaD, thetaH, rgb]
    wi, dw = _hemisphere()
    wi_r = _refract(wi, eta) if m["refractive"] else wi
    t_i = 1 - _fresnel(wi[..., 2], m["ior"])
    cos_i = wi[..., 2]
    alphas = np.geomspace(0.02, 1.0, 60)

    views = (np.arange(N_VIEW) + 0.5) / N_VIEW * (math.pi / 2)
    Cd = np.zeros((N_VIEW, 3)); Cs = np.zeros((N_VIEW, 3)); a_s = np.zeros(N_VIEW)
    th_d_mirror = np.zeros(N_VIEW)
    for k, th in enumerate(views):
        wo = np.array([math.sin(th), 0.0, math.cos(th)])
        wo_r = _refract(wo, eta) if m["refractive"] else wo
        t_o = 1 - _fresnel(wo[2], m["ior"])
        h = wi_r + wo_r
        h /= np.linalg.norm(h, axis=-1, keepdims=True)
        nh, nl, nv = h[..., 2], wi_r[..., 2], wo_r[2]
        vh = np.clip(np.sum(h * wo_r, -1), 1e-6, 1)
        thH = np.arccos(np.clip(nh, 0, 1))
        thD = np.arccos(vh)
        T = _table_lookup(table, thD, thH)
        w = (t_i * t_o * cos_i * dw)[..., None]
        Cd[k] = np.sum(T * (m["kd"] / math.pi) * w, axis=(0, 1)) / t_o
        spec_f = T * _ct(m, nh, nv, nl, vh)[..., None] * (t_i * t_o)[..., None]   # exact outer lobe
        spec_alb = np.sum(spec_f * (cos_i * dw)[..., None], axis=(0, 1))
        lum = spec_f.sum(-1)
        i_m = np.unravel_index(np.argmax(lum), lum.shape)
        shape_exact = lum[i_m] / max(spec_alb.sum(), 1e-12)       # peak per unit albedo
        best = None
        for alpha in alphas:
            fb, alb = _unit_albedo(alpha, wo, wi, cos_i, dw)
            err = abs(math.log(max(fb[i_m] / max(alb, 1e-12), 1e-12) / max(shape_exact, 1e-12)))
            if best is None or err < best[0]:
                best = (err, alpha, alb)
        _, a_s[k], alb_s = best
        Cs[k] = spec_alb / max(alb_s, 1e-12) / t_o
        th_d_mirror[k] = math.asin(math.sin(th) * eta) if m["refractive"] else th

    out = {"views": views, "Cd": Cd, "Cs": Cs, "a_s": a_s, "th_d_mirror": th_d_mirror,
           "flake_rows": 0}
    if m.get("flakes") is not None and m["lut"].size:
        lut = m["lut"]
        rows = lut.shape[0]
        fm = flake_rgb_matrix(m)
        # thetaH = 0 slice of every thetaI row, plus a zero tile past the last row.
        tiles = [m["flakes"][lut[r, 0]] @ fm.T for r in range(rows)]
        tiles.append(np.zeros_like(tiles[0]))
        pos = np.clip(np.stack(tiles), 0, None)       # (rows + 1, V, U, 3) linear Rec.709
        mean_pos = pos.reshape(rows + 1, -1, 3).mean(1)
        # The sparkle shares the specular lobe's per-view width, so taking the clamped
        # flakes' mean energy back out of Cs moves energy within one lobe shape and the
        # mean stays the exact one at every light direction.
        g_f = np.zeros(N_VIEW)
        for k, th in enumerate(views):
            t_o = 1 - _fresnel(math.cos(th), m["ior"])
            # Blender glossy peak (G ~ 1) = colour / (pi a^2 4 cos^2), seen as radiance through
            # the Mix's view-side coat transmission t_o and the light cosine. Match the flake
            # radiance at the mirror, which is the BTF value itself (no transmission, no cosine).
            g_f[k] = math.pi * a_s[k] ** 2 * 4 * math.cos(th) / t_o
            bd = m["num_theta_f"] * th_d_mirror[k] * (2 / math.pi)
            d0 = int(math.floor(bd)); wd = bd - d0
            mp = (1 - wd) * mean_pos[min(d0, rows)] + wd * mean_pos[min(d0 + 1, rows)]
            Cs[k] = np.clip(Cs[k] - mp * g_f[k], 0, None)
        a_f = None
        out.update({"flake_tiles": pos.astype(np.float32), "flake_rows": rows, "a_f": a_f, "g_f": g_f})
    return out
