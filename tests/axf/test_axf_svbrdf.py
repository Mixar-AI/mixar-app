# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""AxF SVBRDF reader + native-BSDF atlas contract (no Blender needed).

Miniature AxF files with the two real HDF5 layouts (Pantora 2026: SummationOperator with
RepresentationClass SVBRDF, spectral maps, GGX; X-Rite 2016 SDK: a com.xrite.Svbrdf node
without RepresentationClass, RGB maps, Ward) pin the reader and the atlas the Cycles
kernel reads (intern/cycles/kernel/svm/closure.h, CLOSURE_BSDF_AXF_SVBRDF_ID).
"""

import os
import re

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

from mixar.modules.axf.core.cpa2_reader import AxfFormatError  # noqa: E402
from mixar.modules.axf.core.payload import (  # noqa: E402
    SVBRDF_ATLAS_VERSION,
    build_svbrdf_atlas,
    spectral_to_rec709_matrix,
)
from mixar.modules.axf.core.svbrdf_reader import (  # noqa: E402
    MODEL_GGX,
    MODEL_WARD,
    MODEL_WARD_COV,
    read_svbrdf,
    representation_class,
)

WL = np.arange(400, 701, 10, dtype=np.float32)
H, W = 3, 5


def _lookup(group, path, location):
    g = group.create_group(path)
    g.attrs["axf.type"] = "com.xrite.ResourceLookupOperator"
    g.create_dataset("ResourceLocations", data=np.array([location], dtype=h5py.string_dtype()))


def _map(res, path, data, *, origin, colorspec=None, mip=False):
    g = res.create_group(path)
    g.attrs["axf.type"] = "com.xrite.MipMap" if mip else "com.xrite.Data"
    if mip:
        g.create_dataset("0/Data", data=data)
    else:
        g.create_dataset("Data", data=data)
    g.create_dataset("TextureOrigin", data=np.bytes_(origin))
    g.create_dataset("WidthMM", data=np.float32(12.0))
    g.create_dataset("HeightMM", data=np.float32(9.0))
    if colorspec:
        g.create_dataset("ColorSpec", data=np.bytes_(colorspec))


def _write_pantora(path, *, extra_resource=None, num_lobes=1, model="com.xrite.GGXSpecularModel"):
    rng = np.random.default_rng(3)
    with h5py.File(path, "w") as f:
        f.create_dataset("com.xrite.ColorSpecs/spectral/Wavelengths", data=WL)
        mat = f.create_group("com.xrite.Materials/pantora")
        res = mat.create_group("com.xrite.Resources")
        spectral = "/com.xrite.ColorSpecs/spectral"
        _map(res, "DiffuseModel/Color", rng.random((H, W, 31)).astype(np.float32) * 0.2,
             origin="BOTTOM_LEFT", colorspec=spectral)
        n = np.zeros((H, W, 3), np.float32); n[..., 1] = rng.uniform(-0.3, 0.3, (H, W)); n[..., 2] = 1.0
        _map(res, "DiffuseModel/Normal", n, origin="BOTTOM_LEFT")
        _map(res, "SpecularModel/Color", rng.random((H, W, 31)).astype(np.float32),
             origin="BOTTOM_LEFT", colorspec=spectral)
        _map(res, "SpecularModel/Lobes", rng.uniform(0.2, 0.4, (H, W, 1)).astype(np.float32),
             origin="BOTTOM_LEFT")
        fr = res.create_group("SpecularModel/Fresnel")
        fr.attrs["axf.type"] = "com.xrite.Uniform"
        fr.create_dataset("Data", data=np.array([0.04], np.float32))

        rep = mat.create_group("com.xrite.Representations/0")
        rep.attrs["axf.type"] = "com.xrite.SummationOperator"
        rep.create_dataset("RepresentationClass", data=np.bytes_("SVBRDF"))
        ops = rep.create_group("com.xrite.Operands")
        lam = ops.create_group("0")
        lam.attrs["axf.type"] = "com.xrite.LambertDiffuseModel"
        _lookup(lam, "com.xrite.Resources/Color", "DiffuseModel/Color")
        _lookup(lam, "com.xrite.Resources/Normal", "DiffuseModel/Normal")
        spec = ops.create_group("1")
        spec.attrs["axf.type"] = model
        spec.create_dataset("Fresnel", data=np.uint8(1))
        spec.create_dataset("FresnelVariant", data=np.bytes_("Schlick1994"))
        spec.create_dataset("Variant", data=np.bytes_(""))
        spec.create_dataset("Anisotropic", data=np.uint8(0))
        spec.create_dataset("NumLobes", data=np.int32(num_lobes))
        _lookup(spec, "com.xrite.Resources/Color", "SpecularModel/Color")
        _lookup(spec, "com.xrite.Resources/Lobes", "SpecularModel/Lobes")
        _lookup(spec, "com.xrite.Resources/Normal", "DiffuseModel/Normal")
        _lookup(spec, "com.xrite.Resources/Fresnel", "SpecularModel/Fresnel")
        if extra_resource:
            _lookup(spec, f"com.xrite.Resources/{extra_resource}", "SpecularModel/Lobes")
    return path


def _write_xrite2016(path, *, lobes=1, variant="", fresnel=0, ward_variant="GeislerMoroder2010"):
    rng = np.random.default_rng(5)
    with h5py.File(path, "w") as f:
        f.create_group("com.xrite.ColorSpecs/sRGB,E")
        mat = f.create_group("com.xrite.Materials/sdk")
        res = mat.create_group("com.xrite.Resources")
        rgb = "$(COLORSPECS)/sRGB,E"
        _map(res, "SVBRDF/Diffuse/Color", rng.random((H, W, 3)).astype(np.float32), origin="TOP_LEFT",
             colorspec=rgb, mip=True)
        n = np.zeros((H, W, 3), np.float32); n[..., :2] = rng.uniform(-0.2, 0.2, (H, W, 2)); n[..., 2] = 1.0
        _map(res, "SVBRDF/Normal", n, origin="TOP_LEFT", mip=True)
        _map(res, "SVBRDF/Specular/Color", rng.random((H, W, 3)).astype(np.float32), origin="TOP_LEFT",
             colorspec=rgb, mip=True)
        _map(res, "SVBRDF/Specular/Lobes", rng.uniform(0.1, 0.5, (H, W, lobes)).astype(np.float32),
             origin="TOP_LEFT", mip=True)
        if lobes == 2:
            _map(res, "SVBRDF/Specular/AnisoRotation", rng.uniform(-1.5, 1.5, (H, W, 1)).astype(np.float32),
                 origin="TOP_LEFT", mip=True)

        rep = mat.create_group("com.xrite.Representations/0")
        rep.attrs["axf.type"] = "com.xrite.Svbrdf"
        ops = rep.create_group("com.xrite.Operands")
        lam = ops.create_group("0")
        lam.attrs["axf.type"] = "com.xrite.LambertDiffuseModel"
        _lookup(lam, "com.xrite.Resources/Color", "SVBRDF/Diffuse/Color")
        _lookup(lam, "com.xrite.Resources/Normal", "SVBRDF/Normal")
        spec = ops.create_group("1")
        spec.attrs["axf.type"] = "com.xrite.WardSpecularModel"
        spec.create_dataset("Variant", data=np.bytes_(ward_variant))
        spec.create_dataset("Anisotropic", data=np.uint8(lobes > 1))
        spec.create_dataset("Fresnel", data=np.uint8(fresnel))
        if variant:
            spec.create_dataset("AnisotropyVariant", data=np.bytes_(variant))
        _lookup(spec, "com.xrite.Resources/Color", "SVBRDF/Specular/Color")
        _lookup(spec, "com.xrite.Resources/Lobes", "SVBRDF/Specular/Lobes")
        _lookup(spec, "com.xrite.Resources/Normal", "SVBRDF/Normal")
        if lobes == 2:
            _lookup(spec, "com.xrite.Resources/AnisoRotation", "SVBRDF/Specular/AnisoRotation")
    return path


def _raw(path, loc):
    with h5py.File(path, "r") as f:
        g = f["com.xrite.Materials"][list(f["com.xrite.Materials"])[0]]["com.xrite.Resources"][loc]
        return (g["Data"] if "Data" in g else g["0/Data"])[()]


def test_pantora_ggx_reads_exactly(tmp_path):
    path = _write_pantora(str(tmp_path / "p.axf"))
    assert representation_class(path) == "SVBRDF"
    m = read_svbrdf(path)
    assert m["model"] == MODEL_GGX and m["fresnel_f0"] == pytest.approx(np.float32(0.04))
    assert m["origin"] == "BOTTOM_LEFT" and m["size_mm"] == (12.0, 9.0)
    M = spectral_to_rec709_matrix(WL)
    np.testing.assert_array_equal(m["diffuse"], _raw(path, "DiffuseModel/Color").astype(np.float64) @ M)
    np.testing.assert_array_equal(m["lobes"][..., 0], _raw(path, "SpecularModel/Lobes")[..., 0])


def test_atlas_matches_kernel_contract_bottom_left(tmp_path):
    path = _write_pantora(str(tmp_path / "p.axf"))
    m = read_svbrdf(path)
    a = build_svbrdf_atlas(m)
    assert a.shape == (H + 1, 4 * W, 4) and a.dtype == np.float32
    # Tiles, rows bottom-up: BOTTOM_LEFT data keeps file row 0 at atlas row 0.
    np.testing.assert_array_equal(a[:H, :W, :3], m["diffuse"].astype(np.float32))
    np.testing.assert_array_equal(a[:H, W:2 * W, :3], m["specular"].astype(np.float32))
    np.testing.assert_array_equal(a[:H, 2 * W:3 * W, 0], _raw(path, "SpecularModel/Lobes")[..., 0])
    np.testing.assert_array_equal(a[:H, 3 * W:, :3], _raw(path, "DiffuseModel/Normal"))
    assert tuple(a[H, 0]) == (SVBRDF_ATLAS_VERSION, MODEL_GGX, np.float32(0.04), 0.0)


def test_sdk_ward_layout_is_flipped_to_bottom_up(tmp_path):
    path = _write_xrite2016(str(tmp_path / "w.axf"))
    assert representation_class(path) == "SVBRDF"     # com.xrite.Svbrdf, no RepresentationClass
    m = read_svbrdf(path)
    assert m["model"] == MODEL_WARD and m["fresnel_f0"] == -1.0 and m["origin"] == "TOP_LEFT"
    a = build_svbrdf_atlas(m)
    # TOP_LEFT: file row 0 is the top edge, so it becomes the atlas's last data row.
    np.testing.assert_array_equal(a[H - 1, :W, :3], _raw(path, "SVBRDF/Diffuse/Color")[0])
    lob = _raw(path, "SVBRDF/Specular/Lobes")[..., 0]
    np.testing.assert_array_equal(a[:H, 2 * W:3 * W, 0], lob[::-1])
    np.testing.assert_array_equal(a[:H, 2 * W:3 * W, 1], lob[::-1])   # isotropic: ax = ay
    assert a[H, 0, 1] == MODEL_WARD


def test_anisotropic_ward_keeps_rotation(tmp_path):
    path = _write_xrite2016(str(tmp_path / "a.axf"), lobes=2)
    m = read_svbrdf(path)
    a = build_svbrdf_atlas(m)
    np.testing.assert_array_equal(a[:H, :W, 3], _raw(path, "SVBRDF/Specular/AnisoRotation")[::-1, :, 0])
    np.testing.assert_array_equal(a[:H, 2 * W:3 * W, :2], _raw(path, "SVBRDF/Specular/Lobes")[::-1])


def test_covariance_ward_keeps_three_parameters(tmp_path):
    path = _write_xrite2016(str(tmp_path / "c.axf"), lobes=3, variant="Covariance")
    m = read_svbrdf(path)
    assert m["model"] == MODEL_WARD_COV
    np.testing.assert_array_equal(build_svbrdf_atlas(m)[:H, 2 * W:3 * W, :3],
                                  _raw(path, "SVBRDF/Specular/Lobes")[::-1])


@pytest.mark.parametrize("kwargs, message", [
    (dict(fresnel=1), "Fresnel"),
    (dict(ward_variant="Duer2010"), "Ward variant"),
    (dict(lobes=3, variant="Other"), "anisotropy variant"),
])
def test_unsupported_ward_is_refused(tmp_path, kwargs, message):
    path = _write_xrite2016(str(tmp_path / "x.axf"), **kwargs)
    with pytest.raises(AxfFormatError, match=message):
        read_svbrdf(path)


@pytest.mark.parametrize("kwargs, message", [
    (dict(num_lobes=2), "Multi-lobe"),
    (dict(extra_resource="Height"), "resources"),
    (dict(model="com.xrite.BlinnPhongSpecularModel"), "not supported"),
])
def test_unsupported_pantora_is_refused(tmp_path, kwargs, message):
    path = _write_pantora(str(tmp_path / "x.axf"), **kwargs)
    with pytest.raises(AxfFormatError, match=message):
        read_svbrdf(path)


def test_model_codes_match_the_kernel():
    here = os.path.dirname(os.path.abspath(__file__))
    header = os.path.join(here, "..", "..", "src", "intern", "cycles", "kernel", "closure",
                          "bsdf_axf_svbrdf.h")
    text = open(header).read()
    codes = dict(re.findall(r"(AXF_SVBRDF_\w+) = (\d+)", text))
    assert int(codes["AXF_SVBRDF_WARD"]) == MODEL_WARD
    assert int(codes["AXF_SVBRDF_WARD_COV"]) == MODEL_WARD_COV
    assert int(codes["AXF_SVBRDF_GGX"]) == MODEL_GGX
