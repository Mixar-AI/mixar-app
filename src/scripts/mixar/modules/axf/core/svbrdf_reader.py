# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read an X-Rite AxF SVBRDF material (per-texel Lambert + Ward or GGX) from its HDF5 file.

Pure numpy + h5py (no bpy), so the scoring harness can import it too.

Supported, each checked against X-Rite's own embedded preview of the sample files
(per pixel, no fitted parameter; see docs/modules/axf.md):
- LambertDiffuseModel + WardSpecularModel, Variant GeislerMoroder2010, no Fresnel:
  isotropic (1 lobe parameter), anisotropic (alpha_x, alpha_y + a rotation map) or the
  "Covariance" variant (a, b, c: slope covariance [[a^2, b], [b, c^2]]);
- LambertDiffuseModel + GGXSpecularModel, one isotropic lobe, Schlick Fresnel with a
  uniform F0 (Pantora 2026) or no Fresnel.
Colours are spectral (31 bands, projected to linear Rec.709 under D65, exact for white
light) or RGB, used as stored (X-Rite's own preview uses 'system' and sRGB,E maps as is).
Anything else is refused with a message rather than approximated.
"""

from __future__ import annotations

import numpy as np

from .cpa2_reader import AxfFormatError, _colorspec, _text, _type

SVBRDF = "SVBRDF"
MODEL_WARD, MODEL_WARD_COV, MODEL_GGX = 0, 1, 2  # bsdf_axf_svbrdf.h AxfSvbrdfModel

_RGB_SPACES = ("sRGB,E", "system", "sRGB,D65")


def representation_class(path: str) -> str:
    """The first representation class of the file's first material ('' if none)."""
    import h5py

    try:
        f = h5py.File(path, "r")
    except OSError as e:
        raise AxfFormatError("Not an AxF file (AxF is HDF5)") from e
    with f:
        mats = f.get("com.xrite.Materials")
        if mats is None or not list(mats.keys()):
            raise AxfFormatError("No AxF material in the file")
        reps = mats[list(mats.keys())[0]]["com.xrite.Representations"]
        classes = [_rep_class(reps[key]) for key in sorted(reps.keys(), key=lambda s: (len(s), s))]
        for wanted in ("CarPaint2", SVBRDF):
            if wanted in classes:
                return wanted
        return classes[0] if classes else ""


def _rep_class(rep) -> str:
    """RepresentationClass, or the representation's own type for files without one
    (the 2016 SDK writes SVBRDFs as a com.xrite.Svbrdf node)."""
    if "RepresentationClass" in rep:
        return _text(rep["RepresentationClass"])
    t = _type(rep).replace("com.xrite.", "")
    return SVBRDF if t.lower() == "svbrdf" else t


def _value(ds):
    v = ds[()]
    return v.item() if isinstance(v, np.ndarray) and v.size == 1 else v


def _flags(model) -> dict:
    out = {}
    for key in model.keys():
        obj = model[key]
        if hasattr(obj, "shape") and obj.size <= 8 and key != "Version":
            out[key] = _text(obj) if obj.dtype.kind in "SO" else _value(obj)
    return out


def _map(material, op, role: str):
    """(data float64 HxWxC with file row 0 first, attrs) of a model resource, or None."""
    res = op["com.xrite.Resources"] if "com.xrite.Resources" in op else None
    if res is None or role not in res:
        return None, None, None
    loc = res[role]["ResourceLocations"][()]
    loc = (loc.ravel()[0] if isinstance(loc, np.ndarray) else loc)
    loc = loc.decode() if isinstance(loc, bytes) else str(loc)
    resources = material["com.xrite.Resources"]
    if loc not in resources:
        raise AxfFormatError(f"AxF resource '{loc}' is missing")
    group = resources[loc]
    attrs = {}
    for key in ("TextureOrigin", "WidthMM", "HeightMM", "ColorSpec", "Layout"):
        if key in group:
            attrs[key] = _text(group[key]) if group[key].dtype.kind in "SO" else float(_value(group[key]))
    data = group["Data"] if "Data" in group else (group["0"]["Data"] if "0" in group else None)
    if data is None:
        raise AxfFormatError(f"AxF resource '{loc}' holds no data")
    if "0" in group and "Data" not in group:
        for key in ("TextureOrigin", "ColorSpec"):  # some files keep these on the level
            if key not in attrs and key in group["0"]:
                attrs[key] = _text(group["0"][key])
    raw = data[()]
    dtype = data.attrs.get("axf.datatype", b"")
    if (dtype.decode() if isinstance(dtype, bytes) else str(dtype)) == "half":
        raw = np.asarray(raw).view(np.float16)
    return np.asarray(raw, np.float64), attrs, loc


def read_svbrdf(path: str) -> dict:
    """Every value X-Rite's SVBRDF decoder uses, as stored (colours projected to Rec.709
    when spectral)."""
    import h5py

    from .payload import spectral_to_rec709_matrix

    try:
        f = h5py.File(path, "r")
    except OSError as e:
        raise AxfFormatError("Not an AxF file (AxF is HDF5)") from e
    with f:
        names = list(f["com.xrite.Materials"].keys())
        material = f[f"com.xrite.Materials/{names[0]}"]
        reps = material["com.xrite.Representations"]
        rep = None
        for key in sorted(reps.keys(), key=lambda s: (len(s), s)):
            if _rep_class(reps[key]) == SVBRDF:
                rep = reps[key]
                break
        if rep is None:
            raise AxfFormatError("No SVBRDF representation in the file")
        ops = rep["com.xrite.Operands"] if "com.xrite.Operands" in rep else None
        if ops is None:
            raise AxfFormatError("SVBRDF representation without operands")
        diffuse = spec = None
        for key in ops.keys():
            t = _type(ops[key]).replace("com.xrite.", "")
            if t == "LambertDiffuseModel":
                diffuse = ops[key]
            elif t in ("WardSpecularModel", "GGXSpecularModel"):
                spec = ops[key]
            else:
                raise AxfFormatError(f"AxF SVBRDF component '{t}' is not supported yet")
        if diffuse is None or spec is None:
            raise AxfFormatError("SVBRDF needs a Lambert diffuse and a Ward or GGX specular model")
        extra = sorted(k for k in rep.keys() if k.startswith("com.xrite.") and k not in (
            "com.xrite.Operands", "com.xrite.PreviewImages", "com.xrite.PreviewImageParameters",
            "com.xrite.Sampler"))
        if extra:
            raise AxfFormatError(f"SVBRDF parts {extra} are not supported yet")

        spec_type = _type(spec).replace("com.xrite.", "")
        flags = _flags(spec)
        anisotropic = bool(flags.get("Anisotropic", 0))
        fresnel = bool(flags.get("Fresnel", 0))
        if int(flags.get("NumLobes", 1)) != 1:
            raise AxfFormatError("Multi-lobe SVBRDF specular models are not supported yet")

        kd, kd_at, _ = _map(material, diffuse, "Color")
        ks, ks_at, _ = _map(material, spec, "Color")
        lobes, lob_at, _ = _map(material, spec, "Lobes")
        normal, n_at, n_loc = _map(material, diffuse, "Normal")
        spec_normal, _, sn_loc = _map(material, spec, "Normal")
        angle, a_at, _ = _map(material, spec, "AnisoRotation")
        known = {"Color", "Lobes", "Normal", "AnisoRotation", "Fresnel"}
        for op in (diffuse, spec):
            res = op["com.xrite.Resources"] if "com.xrite.Resources" in op else {}
            unknown = sorted(k for k in res.keys() if k not in known)
            if unknown:
                raise AxfFormatError(f"SVBRDF resources {unknown} are not supported yet")
        if kd is None or ks is None or lobes is None:
            raise AxfFormatError("SVBRDF is missing its colour or lobe maps")
        if spec_normal is not None and sn_loc != n_loc:
            raise AxfFormatError("Separate diffuse and specular normal maps are not supported yet")

        f0 = -1.0
        if spec_type == "WardSpecularModel":
            variant = str(flags.get("Variant", ""))
            if variant != "GeislerMoroder2010":
                raise AxfFormatError(f"Ward variant '{variant or 'Ward'}' is not supported yet")
            if fresnel:
                raise AxfFormatError("Ward lobes with Fresnel are not supported yet")
            aniso_variant = str(flags.get("AnisotropyVariant", ""))
            if not anisotropic:
                if lobes.shape[-1] != 1:
                    raise AxfFormatError("Unexpected isotropic Ward lobe layout")
                model = MODEL_WARD
                lobe3 = np.concatenate([lobes, lobes, np.zeros_like(lobes)], -1)
            elif aniso_variant == "Covariance":
                if lobes.shape[-1] != 3:
                    raise AxfFormatError("Unexpected covariance Ward lobe layout")
                model = MODEL_WARD_COV
                lobe3 = lobes
            elif aniso_variant == "":
                if lobes.shape[-1] != 2 or angle is None:
                    raise AxfFormatError("Anisotropic Ward needs two lobe parameters and a rotation map")
                model = MODEL_WARD
                lobe3 = np.concatenate([lobes, np.zeros_like(lobes[..., :1])], -1)
            else:
                raise AxfFormatError(f"Ward anisotropy variant '{aniso_variant}' is not supported yet")
        else:
            variant = str(flags.get("Variant", ""))
            if variant:
                raise AxfFormatError(f"GGX variant '{variant}' is not supported yet")
            if anisotropic or lobes.shape[-1] != 1:
                raise AxfFormatError("Anisotropic GGX lobes are not supported yet")
            if fresnel:
                fv = str(flags.get("FresnelVariant", ""))
                if fv not in ("", "Schlick1994"):
                    raise AxfFormatError(f"Fresnel variant '{fv}' is not supported yet")
                fr, _, _ = _map(material, spec, "Fresnel")
                if fr is None or fr.size != 1:
                    raise AxfFormatError("Only a uniform Fresnel F0 is supported")
                f0 = float(fr.ravel()[0])
            model = MODEL_GGX
            lobe3 = np.concatenate([lobes, np.zeros_like(lobes), np.zeros_like(lobes)], -1)

        shape = kd.shape[:2]
        maps = {"diffuse": kd, "specular": ks, "lobes": lobe3, "normal": normal, "angle": angle}
        for key, value in maps.items():
            if value is not None and value.shape[:2] != shape:
                raise AxfFormatError("SVBRDF maps of different sizes are not supported yet")
        size_mm = (float(kd_at.get("WidthMM", 0.0)), float(kd_at.get("HeightMM", 0.0)))
        if not (size_mm[0] > 0 and size_mm[1] > 0):
            raise AxfFormatError("SVBRDF maps without a physical size")
        origins = {at.get("TextureOrigin", "BOTTOM_LEFT") for at in (kd_at, ks_at, lob_at, n_at, a_at) if at}
        if len(origins) != 1:
            raise AxfFormatError("SVBRDF maps with different texture origins are not supported yet")
        origin = origins.pop()
        if origin not in ("TOP_LEFT", "BOTTOM_LEFT"):
            raise AxfFormatError(f"Texture origin '{origin}' is not supported")

        def colour(arr, attrs):
            name, group = _colorspec(f, attrs.get("ColorSpec", ""))
            if group is not None and "Wavelengths" in group and arr.shape[-1] > 3:
                wl = np.asarray(group["Wavelengths"][()], np.float64)
                if len(wl) != arr.shape[-1]:
                    raise AxfFormatError("Spectral map does not match its wavelengths")
                return arr @ spectral_to_rec709_matrix(wl), "spectral"
            if arr.shape[-1] == 3 and (name in _RGB_SPACES or not name):
                return arr, name or "sRGB,E"
            raise AxfFormatError(f"Unsupported colour space '{name or '?'}'")

        kd709, space_d = colour(kd, kd_at)
        ks709, space_s = colour(ks, ks_at)
        if normal is None:
            normal = np.zeros(shape + (3,)); normal[..., 2] = 1.0
        if angle is None:
            angle = np.zeros(shape + (1,))

    return {
        "name": names[0], "extra_materials": names[1:], "representation": SVBRDF,
        "model": model, "spec_type": spec_type, "fresnel_f0": f0,
        "diffuse": kd709, "specular": ks709, "lobes": lobe3, "normal": normal,
        "angle": angle[..., 0], "origin": origin, "size_mm": size_mm,
        "color_space": space_d if space_d == space_s else f"{space_d}/{space_s}",
    }
