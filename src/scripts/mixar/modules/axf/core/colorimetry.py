# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Spectrum -> CIE XYZ -> CIELAB -> CIEDE2000 (pure numpy).

One convention for every AxF accuracy figure (the device check, the lobe refit, the
tests and the shipped accuracy note): CIE 1931 2 degree observer (the observer the AxF
files' own colour specs name), CIE D65 illuminant, Lab relative to the perfect
reflecting diffuser (Y = 100), colour difference CIEDE2000 with kL = kC = kH = 1.
"""

from __future__ import annotations

import numpy as np

from .. import constants as C

OBSERVER = "CIE 1931 2 degree"
ILLUMINANT = "D65"


def _weights(wavelengths) -> np.ndarray:
    """(bands, 3): reflectance spectrum -> XYZ under D65, white Y = 100."""
    wl = np.asarray(wavelengths, np.float64)
    ref = np.asarray(C.WAVELENGTHS, np.float64)
    cmf = np.stack([np.interp(wl, ref, C.CMF_X), np.interp(wl, ref, C.CMF_Y),
                    np.interp(wl, ref, C.CMF_Z)], axis=1)
    s = np.interp(wl, ref, C.D65)
    w = s[:, None] * cmf
    return w * (100.0 / np.sum(w[:, 1]))


def spectrum_to_xyz(spectra, wavelengths) -> np.ndarray:
    """Reflectance (factor) spectra (..., bands) -> XYZ (..., 3), perfect white Y = 100."""
    return np.asarray(spectra, np.float64) @ _weights(wavelengths)


def white_xyz(wavelengths) -> np.ndarray:
    return _weights(wavelengths).sum(axis=0)


def xyz_to_lab(xyz, white) -> np.ndarray:
    t = np.asarray(xyz, np.float64) / np.asarray(white, np.float64)
    d = 6.0 / 29.0
    f = np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], -1)


def spectrum_to_lab(spectra, wavelengths) -> np.ndarray:
    return xyz_to_lab(spectrum_to_xyz(spectra, wavelengths), white_xyz(wavelengths))


def ciede2000(lab1, lab2) -> np.ndarray:
    """CIEDE2000 (Sharma, Wu, Dalal 2005), kL = kC = kH = 1, vectorised over (..., 3)."""
    lab1 = np.asarray(lab1, np.float64)
    lab2 = np.asarray(lab2, np.float64)
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    Cb7 = ((C1 + C2) / 2) ** 7
    G = 0.5 * (1 - np.sqrt(Cb7 / (Cb7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.where((a1p == 0) & (b1 == 0), 0.0, np.degrees(np.arctan2(b1, a1p)) % 360)
    h2p = np.where((a2p == 0) & (b2 == 0), 0.0, np.degrees(np.arctan2(b2, a2p)) % 360)

    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0.0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh) / 2)

    Lbp = (L1 + L2) / 2
    Cbp = (C1p + C2p) / 2
    hsum = h1p + h2p
    hbp = np.where(np.abs(h1p - h2p) > 180,
                   np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2), hsum / 2)
    hbp = np.where(C1p * C2p == 0, hsum, hbp)
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    d_theta = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Cbp7 = Cbp ** 7
    Rc = 2 * np.sqrt(Cbp7 / (Cbp7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * d_theta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                   + Rt * (dCp / Sc) * (dHp / Sh))


def lightness_share(lab1, lab2) -> np.ndarray:
    """Fraction of the squared CIEDE2000 difference that is lightness alone."""
    lab1 = np.asarray(lab1, np.float64)
    lab2 = np.asarray(lab2, np.float64)
    Lb = (lab1[..., 0] + lab2[..., 0]) / 2
    Sl = 1 + 0.015 * (Lb - 50) ** 2 / np.sqrt(20 + (Lb - 50) ** 2)
    dl = (lab2[..., 0] - lab1[..., 0]) / Sl
    de = ciede2000(lab1, lab2)
    return np.where(de > 0, np.minimum((dl / np.maximum(de, 1e-12)) ** 2, 1.0), 1.0)


__all__ = ["OBSERVER", "ILLUMINANT", "spectrum_to_xyz", "white_xyz", "xyz_to_lab",
           "spectrum_to_lab", "ciede2000", "lightness_share"]
