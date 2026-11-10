# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The per-view EEVEE fit of an AxF car paint (no Blender needed).

Pins the image contract the node's EEVEE path reads (64 x 2 RGBA: row 0 = diffuse
albedo + roughness, row 1 = specular albedo + flake gain) and that the albedos are
the exact BRDF's, so the fit cannot drift from what Cycles renders.
"""

import math
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("h5py")

from mixar.modules.axf.core import eevee_fit  # noqa: E402
from mixar.modules.axf.core.approx_fit import N_VIEW, _fresnel  # noqa: E402
from mixar.modules.axf.core.cpa2_reader import read_cpa2  # noqa: E402
from test_axf_cpa2 import _write_mini_axf  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    m = read_cpa2(_write_mini_axf(str(tmp_path_factory.mktemp("fit") / "mini.axf")))
    return m, eevee_fit.fit(m)


def test_lut_layout(fitted):
    _, lut = fitted
    assert lut.shape == (2, N_VIEW, 4) and lut.dtype == np.float32
    assert np.all(np.isfinite(lut))
    assert np.all(lut[0, :, :3] >= 0) and np.all(lut[1, :, :3] >= 0)
    assert np.all((lut[0, :, 3] > 0.0) & (lut[0, :, 3] <= 1.0))  # roughness
    assert np.all(lut[1, :, 3] > 0.0)  # flake gain


def test_diffuse_albedo_is_the_exact_one(fitted):
    """Without lobes, the specular albedo vanishes and the diffuse albedo is the exact
    hemispherical integral (checked here against a finer, independent quadrature)."""
    m, _ = fitted
    m = dict(m, lobes=np.zeros_like(m["lobes"]))
    lut = eevee_fit.fit(m)
    assert np.max(lut[1, :, :3]) == 0.0
    from mixar.modules.axf.core.approx_fit import _refract, _table_lookup
    from mixar.modules.axf.core.payload import table_rgb709

    table = table_rgb709(m)
    wi, dw = eevee_fit._hemisphere(240, 480)
    eta = 1 / m["ior"]
    wi_r = _refract(wi, eta)
    for k in (0, 31, 63):
        th = (k + 0.5) / N_VIEW * math.pi / 2
        wo = np.array([math.sin(th), 0.0, math.cos(th)])
        wo_r = _refract(wo, eta)
        h = wi_r + wo_r
        h /= np.linalg.norm(h, axis=-1, keepdims=True)
        T = _table_lookup(table, np.arccos(np.clip(np.sum(h * wo_r, -1), 0, 1)),
                          np.arccos(np.clip(h[..., 2], 0, 1)), m.get("table_texel_offset", 0.0))
        t = (1 - _fresnel(wi[..., 2], m["ior"])) * (1 - _fresnel(wo[2], m["ior"]))
        exact = np.sum(T * (m["kd"] / math.pi) * (t * wi[..., 2] * dw)[..., None], axis=(0, 1))
        np.testing.assert_allclose(lut[0, k, :3] * (1 - _fresnel(wo[2], m["ior"])), exact,
                                   rtol=2e-2, atol=1e-6)


def test_node_and_importer_share_the_property_name():
    from mixar.modules.axf import constants as C

    node = (ROOT / "src/source/blender/nodes/shader/nodes/"
            "node_shader_bsdf_axf_carpaint.cc").read_text(encoding="utf-8")
    assert f'"{C.PROP_EEVEE_FIT}"' in node and f'"{C.PROP_TABLE}"' in node
    glsl = (ROOT / "src/source/blender/gpu/shaders/material/"
            "gpu_shader_material_axf_carpaint.glsl").read_text(encoding="utf-8")
    assert "node_bsdf_axf_carpaint_fit" in glsl and "node_bsdf_axf_carpaint_fit" in node
