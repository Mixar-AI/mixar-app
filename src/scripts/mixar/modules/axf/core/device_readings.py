# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read the multi-angle device readings an AxF file was fitted from (pure numpy + h5py).

Pantora 2026 car paints keep the X-Rite MA-T12 measurements: per scan
(`com.xrite.Measurements/<n>`), one spectral reading per geometry (6 mm aperture, 31
bands) next to camera images of the same geometries. Each reading's geometry names the
device's emitter (light) and pickup (view) directions, in the sample frame (normal +z).

The stored spectral value is f * cos(theta_emitter): the BRDF times the light cosine,
per unit irradiance from the emitter direction. The reflectance factor the instrument
reports is pi * f = pi * value / cos(theta_emitter).

Files without spectral readings (X-Rite's 2016 library) return no scans.
"""

from __future__ import annotations

import numpy as np


def _s(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, np.ndarray):
        return _s(value.ravel()[0]) if value.size else ""
    return str(value)


def _resolve(f, ref: str):
    """'$(DEVICESPECS)/a/b' -> the group at com.xrite.DeviceSpecs/a/b, or None."""
    if not ref.startswith("$(DEVICESPECS)/"):
        return None
    path = "com.xrite.DeviceSpecs/" + ref[len("$(DEVICESPECS)/"):]
    return f[path] if path in f else None


def _geometry(group) -> dict | None:
    try:
        emitter = np.asarray(group["Emitter/Direction"][()], np.float64)
        pickup = np.asarray(group["Pickup/Direction"][()], np.float64)
    except KeyError:
        return None
    name = _s(group["Name"][()]) if "Name" in group else group.name.rsplit("/", 1)[-1]
    return {"name": name, "emitter": emitter / np.linalg.norm(emitter),
            "pickup": pickup / np.linalg.norm(pickup)}


def read_device_readings(path: str, material: str | None = None) -> dict:
    """{"wavelengths": (bands,), "scans": [{"name", "geometries": {name: {...}}}]}.

    Each geometry entry: emitter, pickup (unit vectors, normal = +z) and value, the
    stored spectrum f * cos(theta_emitter)."""
    import h5py  # Bundled with Mixar (scripts/python_requirements.txt).

    out = {"wavelengths": None, "scans": []}
    with h5py.File(path, "r") as f:
        mats = f["com.xrite.Materials"] if "com.xrite.Materials" in f else None
        if mats is None or not len(mats):
            return out
        mat = mats[material or list(mats.keys())[0]]
        if "com.xrite.Measurements" not in mat or "com.xrite.Resources" not in mat:
            return out
        resources = mat["com.xrite.Resources"]
        measurements = mat["com.xrite.Measurements"]
        for key in sorted(measurements.keys(), key=lambda s: (len(s), s)):
            meas = measurements[key]
            name = key
            meta = meas.get("com.xrite.MeasurementMetadata")
            if meta is not None and "MeasurementName" in meta:
                name = _s(meta["MeasurementName"][()])
            samples = meas.get("com.xrite.MeasurementSamples")
            if samples is None:
                continue
            geometries = {}
            for skey in samples.keys():
                sample = samples[skey]
                if "Geometry" not in sample or "Value/ResourceLocations" not in sample:
                    continue
                locs = sample["Value/ResourceLocations"][()]
                res = resources.get(_s(locs)) if np.size(locs) else None
                if res is None or "Data" not in res:
                    continue
                spec_ref = _s(res["ColorSpec"][()]) if "ColorSpec" in res else ""
                data = np.asarray(res["Data"][()])
                if data.ndim != 1 or not spec_ref.endswith("/spectral"):
                    continue  # camera images (sRGB,D65), sparkle images
                spec_group = f[spec_ref.lstrip("/")] if spec_ref.lstrip("/") in f else None
                if spec_group is None or "Wavelengths" not in spec_group:
                    continue
                wl = np.asarray(spec_group["Wavelengths"][()], np.float64)
                if len(wl) != len(data):
                    continue
                geo_group = _resolve(f, _s(sample["Geometry"][()]))
                geo = _geometry(geo_group) if geo_group is not None else None
                if geo is None or geo["emitter"][2] <= 0 or geo["pickup"][2] <= 0:
                    continue
                if out["wavelengths"] is None:
                    out["wavelengths"] = wl
                elif not np.allclose(out["wavelengths"], wl):
                    continue
                geo["value"] = data.astype(np.float64)
                geometries[geo["name"]] = geo
            if geometries:
                out["scans"].append({"name": name, "geometries": geometries})
    return out


def mean_readings(readings: dict) -> dict:
    """Geometry name -> the reading averaged over every scan that has it (the
    convention every accuracy figure uses), plus 'scans', the count averaged."""
    acc: dict = {}
    for scan in readings["scans"]:
        for name, g in scan["geometries"].items():
            e = acc.setdefault(name, {**g, "value": np.zeros_like(g["value"]), "scans": 0})
            e["value"] = e["value"] + g["value"]
            e["scans"] += 1
    for e in acc.values():
        e["value"] = e["value"] / e["scans"]
    return acc


def geometry_order(names) -> list:
    """Stable display order: pickup group, then aspecular angle (r45as-15 ... r15as80)."""
    def key(n):
        try:
            head, asp = n.split("as", 1)
            return (0, -float(head.lstrip("r")), float(asp), n)
        except ValueError:
            return (1, 0.0, 0.0, n)
    return sorted(names, key=key)
