# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""AxF CarPaint2 reader + native-BSDF payload contract (no Blender needed).

A miniature AxF file with the real HDF5 layout is written with h5py, so the
reader and the image layout the Cycles kernel reads
(intern/cycles/kernel/closure/bsdf_axf_carpaint.h) are pinned without the
140 MB production sample.
"""

import math

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

from mixar.modules.axf import constants as C  # noqa: E402
from mixar.modules.axf.core.cpa2_reader import AxfFormatError, read_cpa2  # noqa: E402
from mixar.modules.axf.core.payload import (  # noqa: E402
    build_payload,
    complete_table,
    flake_rgb_matrix,
    spectral_to_rec709_matrix,
    table_rgb709,
)

WL = np.arange(400, 701, 10, dtype=np.float32)


def _lookup(group, path, locations):
    g = group.create_group(path)
    g.attrs["axf.type"] = "com.xrite.ResourceLookupOperator"
    g.create_dataset("ResourceLocations", data=np.array(locations, dtype=h5py.string_dtype()))


def _write_mini_axf(path, *, rep_class="CarPaint2"):
    rng = np.random.default_rng(7)
    with h5py.File(path, "w") as f:
        cs = f.create_group("com.xrite.ColorSpecs")
        cs.create_dataset("spectral/Wavelengths", data=WL)
        cs.create_dataset("sRGB,E/ToSpectralMatrix/Data", data=rng.random((3, 61)).astype(np.float32))
        cs.create_dataset("sRGB,E/ToSpectralMatrix/Wavelengths", data=np.arange(400, 701, 5, dtype=np.float32))
        cs.create_dataset("sRGB,E/com.xrite.ColorMatrices/XYZ", data=np.eye(3, dtype=np.float32))
        mat = f.create_group("com.xrite.Materials/mini")
        res = mat.create_group("com.xrite.Resources")
        res.create_dataset("CarPaint2/DiffuseModel/Color/Data", data=np.array([0.02], np.float32))
        for i, lobe in enumerate([(0.004, 0.14, 0.5), (0.0, 0.35, 0.04)]):
            res.create_dataset(f"CarPaint2/SpecularModel/Lobes/{i}/Data", data=np.array(lobe, np.float32))
        table = np.zeros((8, 6, 31), np.float32)          # [thetaD, thetaH, band]
        table[...] = (np.arange(8)[:, None, None] * 10 + np.arange(6)[None, :, None]).astype(np.float32)
        res.create_dataset("TabulatedBrdf/Color/Data", data=table)
        res.create_dataset("TabulatedBrdf/Color/ColorSpec", data=np.bytes_("$(COLORSPECS)/spectral"))
        res.create_dataset("ClearCoatFilter/IOR/Data", data=np.array([1.5], np.float32))
        flakes = res.create_group("CarPaint2/Flakes")
        flakes.create_dataset("WidthMM", data=np.float32(25.6))
        flakes.create_dataset("HeightMM", data=np.float32(25.6))
        for i in range(3):
            flakes.create_dataset(f"Patch{i}/Data", data=(rng.standard_normal((4, 4, 3)) * 0.1)
                                  .astype(np.float16).view(np.uint16))
            flakes[f"Patch{i}/Data"].attrs["axf.datatype"] = "half"

        rep = mat.create_group("com.xrite.Representations/0")
        rep.attrs["axf.type"] = "com.xrite.ClearCoatFilter"
        rep.create_dataset("RepresentationClass", data=np.bytes_(rep_class))
        rep.create_dataset("NoRefraction", data=np.uint8(0))
        rep.create_dataset("UseSolidAngleCompression", data=np.uint8(0))
        _lookup(rep, "com.xrite.Resources/IOR", ["ClearCoatFilter/IOR"])
        ops = rep.create_group("com.xrite.Input/com.xrite.Operands")
        fl = ops.create_group("0")
        fl.attrs["axf.type"] = "com.xrite.FlakesBtf"
        fl.create_dataset("NumThetaF", data=np.int32(14))
        fl.create_dataset("NumThetaI", data=np.int32(14))
        fl.create_dataset("PatchesLookupTable", data=np.array([[0, 1], [2, -1]], np.int32))
        fl.create_dataset("Type", data=np.bytes_("ThetaFI"))
        _lookup(fl, "com.xrite.Resources/Data", [f"CarPaint2/Flakes/Patch{i}" for i in range(3)])
        mul = ops.create_group("1/com.xrite.Operands")
        tb = mul.create_group("0")
        tb.attrs["axf.type"] = "com.xrite.TabulatedBrdf"
        _lookup(tb, "com.xrite.Resources/Data", ["TabulatedBrdf/Color"])
        summ = mul.create_group("1/com.xrite.Operands")
        lam = summ.create_group("0")
        lam.attrs["axf.type"] = "com.xrite.LambertDiffuseModel"
        _lookup(lam, "com.xrite.Resources/Color", ["CarPaint2/DiffuseModel/Color"])
        ct = summ.create_group("1")
        ct.attrs["axf.type"] = "com.xrite.CookTorranceSpecularModel"
        ct.create_dataset("FresnelVariant", data=np.bytes_("Schlick1994"))
        ct.create_dataset("NumLobes", data=np.int32(2))
        _lookup(ct, "com.xrite.Resources/Lobes",
                ["CarPaint2/SpecularModel/Lobes/0", "CarPaint2/SpecularModel/Lobes/1"])
    return path


@pytest.fixture()
def mini_axf(tmp_path):
    return _write_mini_axf(str(tmp_path / "mini.axf"))


def test_reader_keeps_values_exact(mini_axf):
    m = read_cpa2(mini_axf)
    assert m["kd"] == pytest.approx(np.float32(0.02))
    np.testing.assert_array_equal(m["lobes"][0], np.array((0.004, 0.14, 0.5), np.float32))
    assert m["ior"] == 1.5 and m["refractive"]
    assert m["table"].shape == (8, 6, 31) and m["table_space"] == "spectral"
    assert m["coat_normal"] is None
    assert m["flakes"].shape == (3, 4, 4, 3)
    assert m["flakes"].dtype == np.float32
    np.testing.assert_array_equal(m["lut"], [[0, 1], [2, -1]])


def test_reader_refuses_other_representations(tmp_path):
    path = _write_mini_axf(str(tmp_path / "svbrdf.axf"), rep_class="SVBRDF")
    with pytest.raises(AxfFormatError):
        read_cpa2(path)


def test_param_stream_matches_kernel_contract(mini_axf):
    m = read_cpa2(mini_axf)
    p = build_payload(m)
    img = p["table_image"]
    nh = 6
    assert img.shape[1] == nh
    stream = img[:p["table_row0"]].reshape(-1, 4)
    assert tuple(stream[0]) == (C.PARAM_VERSION, np.float32(0.02), 1.5, 1.0)
    assert tuple(stream[1]) == (2, 14, 2, 2)                     # lobes, numThetaF, lut rows/cols
    assert tuple(stream[2]) == (C.ATLAS_COLUMNS, 4, 4, 8)        # atlas cols, patch w/h, table h
    assert tuple(stream[3][:3]) == (p["table_row0"], C.ATLAS_COLUMNS * 4, 4)  # + atlas w, h
    np.testing.assert_array_equal(stream[4:7, :3], p["flake_matrix"].astype(np.float32))
    np.testing.assert_array_equal(stream[C.PARAM_HEADER_TEXELS, :3], np.float32([0.004, 0.14, 0.5]))
    lut_texel = stream[C.PARAM_HEADER_TEXELS + 2]
    np.testing.assert_array_equal(lut_texel, [0, 1, 2, -1])
    # Colour table rows follow: row = thetaD, column = thetaH.
    table_rgb = img[p["table_row0"]:, :, :3]
    expect = m["table"] @ spectral_to_rec709_matrix(m["wavelengths"])
    np.testing.assert_array_equal(table_rgb, expect.astype(np.float32))


def test_flake_atlas_keeps_stored_values(mini_axf):
    m = read_cpa2(mini_axf)
    atlas = build_payload(m)["flake_atlas"]
    for i in range(3):
        r, c = divmod(i, C.ATLAS_COLUMNS)
        np.testing.assert_array_equal(atlas[r * 4:(r + 1) * 4, c * 4:(c + 1) * 4, :3], m["flakes"][i])


def test_white_reflector_is_white():
    s2rgb = spectral_to_rec709_matrix(WL)
    np.testing.assert_allclose(np.ones(31) @ s2rgb, [1, 1, 1], rtol=1e-12)


def test_flake_matrix_is_xyz_basis_composition(mini_axf):
    m = read_cpa2(mini_axf)
    fm = flake_rgb_matrix(m)
    rgb = np.array([0.3, -0.1, 0.7])
    to_spec = np.stack([np.interp(WL, m["to_spectral_wl"], m["to_spectral"][k]) for k in range(3)])
    spec = (rgb @ m["rgb_e_to_xyz"]) @ to_spec
    np.testing.assert_allclose(fm @ rgb, spec @ spectral_to_rec709_matrix(WL), rtol=1e-12)
    assert math.isfinite(float(fm.sum()))


def test_reader_refuses_virtual_theta_i_slices(tmp_path):
    path = _write_mini_axf(str(tmp_path / "virtual.axf"))
    with h5py.File(path, "a") as f:
        ds = f["com.xrite.Materials/mini/com.xrite.Representations/0/com.xrite.Input/com.xrite.Operands/0/NumThetaI"]
        ds[()] = 7
    with pytest.raises(AxfFormatError):
        read_cpa2(path)


def test_reader_refuses_unknown_coat_resources(tmp_path):
    path = _write_mini_axf(str(tmp_path / "coatcolor.axf"))
    with h5py.File(path, "a") as f:
        rep = f["com.xrite.Materials/mini/com.xrite.Representations/0"]
        _lookup(rep, "com.xrite.Resources/Color", ["ClearCoatFilter/IOR"])
    with pytest.raises(AxfFormatError):
        read_cpa2(path)


def _make_2016_style(path):
    """The 2016 X-Rite library layout: an older representation listed first, an RGB
    (sRGB,E) colour table with no spectral colour spec, a clear coat normal map, and no
    NoRefraction flag."""
    rng = np.random.default_rng(3)
    with h5py.File(path, "a") as f:
        del f["com.xrite.ColorSpecs/spectral"]
        del f["com.xrite.ColorSpecs/sRGB,E/ToSpectralMatrix"]
        mat = f["com.xrite.Materials/mini"]
        res = mat["com.xrite.Resources"]
        del res["TabulatedBrdf/Color/Data"]
        del res["TabulatedBrdf/Color/ColorSpec"]
        table = np.zeros((8, 8, 3), np.float32)
        d, h = np.meshgrid(np.arange(8), np.arange(8), indexing="ij")
        inside = d + h <= 5
        table[inside] = rng.random((int(inside.sum()), 3)).astype(np.float32) + 0.1
        res.create_dataset("TabulatedBrdf/Color/Data", data=table)
        res["TabulatedBrdf/Color"].create_dataset("ColorSpec", data=np.bytes_("$(COLORSPECS)/sRGB,E"))
        normal = rng.normal(0, 0.01, (6, 5, 3)).astype(np.float32)
        normal[..., 2] = 1.0
        normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
        res.create_dataset("ClearCoat/Normal/Data", data=normal)
        res.create_dataset("ClearCoat/Normal/WidthMM", data=np.float32(35.0))
        res.create_dataset("ClearCoat/Normal/HeightMM", data=np.float32(34.0))
        res.create_dataset("ClearCoat/Normal/Layout", data=np.array(["V", "U", "X,Y,Z"], dtype=h5py.string_dtype()))
        reps = mat["com.xrite.Representations"]
        reps.move("0", "1")
        rep = reps["1"]
        del rep["NoRefraction"]
        _lookup(rep, "com.xrite.Resources/Normal", ["ClearCoat/Normal"])
        old = reps.create_group("0")
        old.attrs["axf.type"] = "com.xrite.Carpaint"
    return path, table, normal


def test_reader_2016_layout(tmp_path):
    path, table, normal = _make_2016_style(_write_mini_axf(str(tmp_path / "old.axf")))
    m = read_cpa2(path)
    assert m["table_space"] == "srgb_e" and m["wavelengths"] is None
    np.testing.assert_array_equal(m["table"], table)
    np.testing.assert_array_equal(m["coat_normal"], normal)
    assert m["coat_normal_mm"] == (35.0, 34.0)
    assert m["refractive"]  # no NoRefraction flag = refractive (X-Rite's previews agree)
    np.testing.assert_array_equal(flake_rgb_matrix(m), np.eye(3))
    p = build_payload(m)
    coat = p["coat_normal_image"]
    np.testing.assert_array_equal(coat[..., :3], normal)
    assert np.all(coat[..., 3] == 1.0)


def test_complete_table_follows_xrite_fill():
    rng = np.random.default_rng(5)
    n, e = 8, 5
    d, h = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    table = np.where((d + h <= e)[..., None], rng.random((n, n, 3)) + 0.1, 0.0)
    full = complete_table(table)
    inside = d + h <= e
    np.testing.assert_array_equal(full[inside], table[inside])
    for di, hi in zip(*np.nonzero(~inside)):
        hc = min(hi, e)
        np.testing.assert_array_equal(full[di, hi], table[min(di, e - hc), hc])
    # A complete table, or zeros that are not that triangle, is left alone.
    np.testing.assert_array_equal(complete_table(full), full)
    odd = table.copy(); odd[0, 0] = 0.0
    np.testing.assert_array_equal(complete_table(odd), odd)


def test_rgb_table_reaches_the_kernel_completed(tmp_path):
    path, table, _ = _make_2016_style(_write_mini_axf(str(tmp_path / "old.axf")))
    m = read_cpa2(path)
    p = build_payload(m)
    np.testing.assert_array_equal(p["table_image"][p["table_row0"]:, :, :3],
                                  complete_table(table.astype(np.float64)).astype(np.float32))
    np.testing.assert_array_equal(table_rgb709(m), complete_table(table.astype(np.float64)))
