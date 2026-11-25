# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""AxF device readings, the model-vs-device check and the opt-in lobe refit (no Blender).

The real Pantora 2026 scans are customer data and are not in the repository; these
tests use a miniature file with the real HDF5 layout of the readings and synthetic
paints whose ground truth is known."""

import math

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

from mixar.modules.axf.core import colorimetry as cm  # noqa: E402
from mixar.modules.axf.core import device_check as dc  # noqa: E402
from mixar.modules.axf.core import device_fit as df  # noqa: E402
from mixar.modules.axf.core import model_eval  # noqa: E402
from mixar.modules.axf.core.device_readings import (  # noqa: E402
    geometry_order,
    mean_readings,
    read_device_readings,
)
from mixar.modules.axf.core.eevee_fit import fit as eevee_fit  # noqa: E402
from mixar.modules.axf.core.eevee_upgrade import model_from_table_pixels  # noqa: E402
from mixar.modules.axf.core.payload import build_payload, build_table_image_like  # noqa: E402

WL = np.arange(400, 701, 10, dtype=np.float64)
# The MA-T12 geometries: (pickup angle, aspecular angle), emitter at pickup - aspecular.
GEOMETRIES = [(45, a) for a in (-15, 15, 25, 45, 75, 110)] + [(15, a) for a in (-45, -30, -15, 15, 45, 80)]


def _directions(pickup_deg, aspec_deg):
    p, e = math.radians(pickup_deg), math.radians(pickup_deg - aspec_deg)
    return np.array([0.0, -math.sin(e), math.cos(e)]), np.array([0.0, math.sin(p), math.cos(p)])


def _paint(lobes, kd=0.1, tint=(0.3, 0.5, 0.8)):
    """A spectral car paint: a smooth table that darkens with thetaH, no flakes."""
    nd = nh = 16
    hue = np.interp(WL, [400, 550, 700], tint)
    fall = np.exp(-np.linspace(0, 2, nh))[None, :, None] * (1 - 0.2 * np.linspace(0, 1, nd))[:, None, None]
    return {"kd": kd, "lobes": np.asarray(lobes, np.float64), "ior": 1.5, "refractive": True,
            "table": fall * hue[None, None, :], "table_space": "spectral", "wavelengths": WL,
            "table_texel_offset": 0.5, "flakes": None, "lut": np.zeros((0, 0), np.int64),
            "num_theta_f": 0, "to_spectral": None, "to_spectral_wl": None, "rgb_e_to_xyz": None}


def _readings(m, scans=2, noise=0.0, seed=1):
    """Readings a device would store for paint m: f * cos(theta_emitter) per geometry."""
    rng = np.random.default_rng(seed)
    prep = model_eval.prepare(m)
    out = {"wavelengths": WL, "scans": []}
    for s in range(scans):
        geos = {}
        for pk, asp in GEOMETRIES:
            light, view = _directions(pk, asp)
            v = model_eval.eval_cos(m, prep, light, view) * (1 + noise * rng.standard_normal())
            geos[f"r{pk}as{asp}"] = {"name": f"r{pk}as{asp}", "emitter": light, "pickup": view, "value": v}
        out["scans"].append({"name": f"scan {s + 1}", "geometries": geos})
    return out


# Sharma, Wu and Dalal (2005), Table 1: CIEDE2000 test pairs.
SHARMA = [
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
    ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
]


@pytest.mark.parametrize("lab1,lab2,expected", SHARMA)
def test_ciede2000_matches_published_pairs(lab1, lab2, expected):
    assert float(cm.ciede2000(lab1, lab2)) == pytest.approx(expected, abs=1e-4)
    assert float(cm.ciede2000(lab2, lab1)) == pytest.approx(expected, abs=1e-4)


def test_perfect_white_is_lab_100():
    np.testing.assert_allclose(cm.spectrum_to_lab(np.ones(31), WL), [100, 0, 0], atol=1e-9)


def _add_readings(path, readings):
    """Write readings into an AxF file with X-Rite's layout: per-scan samples that point
    at device geometries, spectral resources next to camera images."""
    with h5py.File(path, "a") as f:
        if "com.xrite.ColorSpecs/spectral/Wavelengths" not in f:
            f.create_dataset("com.xrite.ColorSpecs/spectral/Wavelengths", data=WL.astype(np.float32))
        dev = f.create_group("com.xrite.DeviceSpecs/X-Rite.MA-T12.1/com.xrite.Geometries")
        mat = f[f"com.xrite.Materials/{list(f['com.xrite.Materials'].keys())[0]}"]
        res = mat.require_group("com.xrite.Resources").create_group("Measurements")
        for s, scan in enumerate(readings["scans"]):
            meas = mat.create_group(f"com.xrite.Measurements/{s}")
            meas.create_dataset("com.xrite.MeasurementMetadata/MeasurementName", data=np.bytes_(scan["name"]))
            for i, (name, g) in enumerate(scan["geometries"].items()):
                if s == 0:
                    geo = dev.create_group(name)
                    geo.create_dataset("Name", data=np.bytes_(name))
                    geo.create_dataset("Emitter/Direction", data=g["emitter"])
                    geo.create_dataset("Pickup/Direction", data=g["pickup"])
                spec = res.create_group(f"{scan['name']} {name}")
                spec.create_dataset("ColorSpec", data=np.bytes_("/com.xrite.ColorSpecs/spectral"))
                spec.create_dataset("Data", data=g["value"].astype(np.float32))
                cam = res.create_group(f"{scan['name']} {name}_1")
                cam.create_dataset("ColorSpec", data=np.bytes_("/com.xrite.ColorSpecs/sRGB,D65"))
                cam.create_dataset("Data", data=np.zeros((3, 4, 3), np.uint16))
                # Locations are relative to the material's resources, as X-Rite writes them.
                for k, loc in ((2 * i, f"Measurements/{scan['name']} {name}"),
                               (2 * i + 1, f"Measurements/{scan['name']} {name}_1")):
                    smp = meas.create_group(f"com.xrite.MeasurementSamples/{k}")
                    geo_ref = f"$(DEVICESPECS)/X-Rite.MA-T12.1/com.xrite.Geometries/{name}"
                    smp.create_dataset("Geometry", data=np.bytes_(geo_ref))
                    smp.create_dataset("Value/ResourceLocations", data=np.array([loc], dtype=h5py.string_dtype()))


def test_reader_reads_spectral_readings_and_skips_camera_images(tmp_path):
    m = _paint([(0.05, 0.15, 0.5), (0, 0.35, 0.04)])
    truth = _readings(m, scans=2, noise=0.01)
    path = str(tmp_path / "readings.axf")
    with h5py.File(path, "w") as f:
        f.create_group("com.xrite.Materials/paint")
    _add_readings(path, truth)
    got = read_device_readings(path)
    np.testing.assert_allclose(got["wavelengths"], WL)
    assert [s["name"] for s in got["scans"]] == ["scan 1", "scan 2"]
    assert set(got["scans"][0]["geometries"]) == {f"r{p}as{a}" for p, a in GEOMETRIES}
    g = got["scans"][1]["geometries"]["r15as45"]
    np.testing.assert_allclose(g["value"], truth["scans"][1]["geometries"]["r15as45"]["value"], rtol=1e-6)
    np.testing.assert_allclose(g["emitter"], truth["scans"][1]["geometries"]["r15as45"]["emitter"])
    mean = mean_readings(got)
    assert mean["r45as25"]["scans"] == 2
    assert geometry_order(mean)[:2] == ["r45as-15", "r45as15"]


def test_file_without_readings_has_no_scans(tmp_path):
    path = str(tmp_path / "none.axf")
    with h5py.File(path, "w") as f:
        f.create_group("com.xrite.Materials/paint")
    assert read_device_readings(path)["scans"] == []


def test_fast_path_equals_point_evaluation():
    m = _paint([(0.05, 0.15, 0.5), (0.01, 0.4, 0.5), (0, 0.35, 0.04)])
    d = dc.prepare(m, _readings(m, scans=1))
    prep = model_eval.prepare(m)
    xyz = dc.model_xyz(d)
    for i, name in enumerate(d["names"]):
        pk, asp = name[1:].split("as")
        light, view = _directions(int(pk), int(asp))
        ref = cm.spectrum_to_xyz(model_eval.eval_cos(m, prep, light, view) * math.pi / light[2], WL)
        np.testing.assert_allclose(xyz[i], ref, rtol=1e-12)


def test_model_matches_its_own_readings():
    m = _paint([(0.05, 0.15, 0.5), (0, 0.35, 0.04)])
    r = dc.report(dc.prepare(m, _readings(m)))
    assert r["max"] < 1e-9
    assert r["convention"].startswith("CIEDE2000, D65, CIE 1931 2 degree")


def test_refit_recovers_a_two_lobe_paint_stored_with_one_lobe():
    truth = _paint([(0.04, 0.12, 0.5), (0.03, 0.35, 0.5), (0, 0.35, 0.04)])
    stored = _paint([(0.06, 0.16, 0.5), (0, 0.35, 0.04), (0, 0.35, 0.04)])
    d = dc.prepare(stored, _readings(truth, noise=0.002))
    res = df.refit(stored, d)
    assert res["accepted"], res["reason"]
    assert res["held_out_mean"] < res["file"]["mean"] - df.MIN_GAIN
    assert res["refit"]["max"] < 0.5 < res["file"]["max"]
    assert res["lobes"].shape == (3, 3)
    np.testing.assert_array_equal(res["lobes"][:, 2], [0.5, 0.5, 0.04])  # F0 stays the file's


# Brightness factors (log) a real Pantora silver needs per MA-T12 geometry, in GEOMETRIES
# order (research of 2026-11-25): the shoulder too dark, the peak and the flop too bright.
# Not a CarPaint2 shape, so a refit matches the instrument's angles but not between them.
SILVER_LOG_FACTORS = [0.01, -0.13, -0.13, 0.29, 0.01, -0.17, 0.24, -0.01, 0.04, 0.0, 0.39, -0.01]


def test_refit_is_refused_when_it_does_not_hold_between_the_instruments_angles():
    stored = _paint([(0.06, 0.16, 0.5), (0, 0.35, 0.04), (0, 0.35, 0.04)])
    readings = _readings(stored)
    for scan in readings["scans"]:
        for (pk, asp), k in zip(GEOMETRIES, SILVER_LOG_FACTORS):
            scan["geometries"][f"r{pk}as{asp}"]["value"] = scan["geometries"][f"r{pk}as{asp}"]["value"] * np.exp(k)
    d = dc.prepare(stored, readings)
    res = df.refit(stored, d)
    assert not res["accepted"]
    assert res["reason"] == df.REASON_ANGLES, res["reason"]
    assert res["held_out_angles_mean"] > res["file"]["mean"]
    assert len(res["held_out_angles"]) == len(GEOMETRIES)


def test_angle_groups_follow_the_half_angle():
    d = dc.prepare(_paint([(0.06, 0.16, 0.5)]), _readings(_paint([(0.06, 0.16, 0.5)])))
    g = df.angle_groups(d)
    th = np.degrees(np.arccos(np.clip(d["nh"], -1, 1)))
    order = np.argsort(th)
    for a, b in zip(order[:-1], order[1:]):
        # Neighbours in half-angle share a group exactly when they are close.
        assert (g[a] == g[b]) == (th[b] - th[a] <= df.GROUP_SPREAD_DEG)
    assert 3 <= len(set(g.tolist())) < len(th)


def test_refit_is_refused_when_the_file_already_matches():
    m = _paint([(0.05, 0.15, 0.5), (0, 0.35, 0.04)])
    res = df.refit(m, dc.prepare(m, _readings(m, noise=0.003)))
    assert not res["accepted"]
    assert res["reason"] == df.REASON_MEAN
    np.testing.assert_array_equal(res["lobes"], m["lobes"])


def test_refit_changes_only_the_lobe_texels():
    m = _paint([(0.06, 0.16, 0.5), (0, 0.35, 0.04), (0, 0.35, 0.04)])
    payload = build_payload(m)
    refit = {**m, "lobes": np.array([(0.04, 0.12, 0.5), (0.03, 0.35, 0.5), (0, 0.35, 0.04)])}
    img = build_table_image_like(refit, payload)
    diff = np.argwhere(np.any(img != payload["table_image"], axis=-1))
    stream_index = diff[:, 0] * img.shape[1] + diff[:, 1]
    assert set(stream_index.tolist()) <= {7, 8, 9}  # PARAM_HEADER_TEXELS + lobe index


def test_eevee_fit_from_the_table_image_matches_the_import_fit():
    m = _paint([(0.05, 0.15, 0.5), (0.01, 0.4, 0.5), (0, 0.35, 0.04)])
    rows = build_payload(m)["table_image"]
    rebuilt = model_from_table_pixels(rows)
    assert rebuilt["kd"] == pytest.approx(m["kd"]) and rebuilt["refractive"]
    assert rebuilt["table_texel_offset"] == 0.5
    np.testing.assert_allclose(eevee_fit(rebuilt), eevee_fit(m), rtol=2e-5, atol=1e-6)


def test_table_pixels_that_are_not_a_table_are_refused():
    with pytest.raises(ValueError):
        model_from_table_pixels(np.zeros((4, 4, 4), np.float32))
