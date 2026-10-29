# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read an X-Rite AxF CarPaint2 (CPA2) material straight from its HDF5 file.

Pure numpy + h5py (no bpy), so the scoring harness can import it too.

Two generations of CarPaint2 files are read:
- spectral (Pantora 2026+): colour table in 31 spectral bands, flake colour through the
  file's ToSpectralMatrix;
- RGB (2016-era X-Rite library): colour table in linear sRGB primaries (E white), a
  clear coat normal map, and sometimes an older representation listed first.

Semantics that the raw file does not spell out were decided against X-Rite's own
data (the measurements and the CPUDecoder preview in the file); see
docs/modules/axf.md:
- the colour table is stored [thetaD][thetaH] (its Layout label reads H, D);
- each CT lobe is stored (coefficient, spread m, F0);
- ToSpectralMatrix maps XYZ (not RGB) to spectral bands.
"""

from __future__ import annotations

import hashlib

import numpy as np

CARPAINT2 = "CarPaint2"
SPECTRAL = "spectral"
SRGB_E = "srgb_e"
# Cook-Torrance variants that are the CarPaint2 lobe (the 2016 files name it).
_CT_VARIANTS = ("", "GeislerMoroder2010")


class AxfFormatError(ValueError):
    """The file is not an AxF CarPaint2 material this importer understands."""


def _text(ds) -> str:
    value = ds[()]
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    if isinstance(value, np.ndarray) and value.dtype.kind in "SO":
        return " ".join(v.decode() if isinstance(v, bytes) else str(v) for v in value.ravel())
    return str(value)


def _type(group) -> str:
    t = group.attrs.get("axf.type", b"")
    return t.decode() if isinstance(t, bytes) else str(t)


def _children(group):
    return [group[k] for k in sorted(group.keys(), key=lambda s: (len(s), s))]


def _find_rep(group, type_name):
    """Depth-first search of a representation tree for a node of the given axf.type."""
    if _type(group) == type_name:
        return group
    for key in group:
        child = group[key]
        if hasattr(child, "keys"):
            found = _find_rep(child, type_name)
            if found is not None:
                return found
    return None


def _resource(material, lookup_group):
    """Resolve a ResourceLookupOperator into the referenced resource groups."""
    locations = lookup_group["ResourceLocations"][()]
    resources = material["com.xrite.Resources"]
    out = []
    for loc in locations.ravel():
        loc = loc.decode() if isinstance(loc, bytes) else str(loc)
        if loc not in resources:
            raise AxfFormatError(f"AxF resource '{loc}' is missing")
        out.append(resources[loc])
    return out


def _colorspec(f, ref: str):
    """'$(COLORSPECS)/name' -> (name, group or None)."""
    name = ref.rsplit("/", 1)[-1] if ref else ""
    specs = f["com.xrite.ColorSpecs"] if "com.xrite.ColorSpecs" in f else None
    return name, (specs[name] if specs is not None and name in specs else None)


def _pick_representation(material):
    """The CarPaint2 representation (2016 files may list an older one first)."""
    reps = material["com.xrite.Representations"]
    found = []
    for key in sorted(reps.keys(), key=lambda s: (len(s), s)):
        rep = reps[key]
        rep_class = _text(rep["RepresentationClass"]) if "RepresentationClass" in rep else ""
        if rep_class == CARPAINT2:
            return rep
        found.append(rep_class or _type(rep))
    raise AxfFormatError(
        f"AxF representation '{', '.join(found)}' is not supported "
        f"(this importer reads {CARPAINT2} car paints)"
    )


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_cpa2(path: str, *, load_flakes: bool = True) -> dict:
    """Return every value the CarPaint2 BRDF uses, exactly as stored."""
    import h5py  # Bundled with Mixar (scripts/python_requirements.txt).

    try:
        f = h5py.File(path, "r")
    except OSError as e:
        raise AxfFormatError("Not an AxF file (AxF is HDF5)") from e

    with f:
        if "com.xrite.Materials" not in f:
            raise AxfFormatError("No AxF material in the file")
        names = list(f["com.xrite.Materials"].keys())
        if not names:
            raise AxfFormatError("The AxF file holds no material")
        name = names[0]
        extra_materials = names[1:]
        material = f[f"com.xrite.Materials/{name}"]
        root = _pick_representation(material)

        lambert = _find_rep(root, "com.xrite.LambertDiffuseModel")
        ct = _find_rep(root, "com.xrite.CookTorranceSpecularModel")
        tab = _find_rep(root, "com.xrite.TabulatedBrdf")
        flakes = _find_rep(root, "com.xrite.FlakesBtf")
        if lambert is None or ct is None or tab is None:
            raise AxfFormatError("CarPaint2 representation is incomplete")

        kd = float(np.asarray(_resource(material, lambert["com.xrite.Resources/Color"])[0]["Data"][()]).ravel()[0])
        lobes = np.array(
            [np.asarray(g["Data"][()], np.float64) for g in
             _resource(material, ct["com.xrite.Resources/Lobes"])],
            np.float64,
        )
        if lobes.ndim != 2 or lobes.shape[1] != 3:
            raise AxfFormatError("Unexpected Cook-Torrance lobe layout")
        fresnel_variant = _text(ct["FresnelVariant"]) if "FresnelVariant" in ct else ""
        if fresnel_variant not in ("", "Schlick1994"):
            raise AxfFormatError(f"Unsupported Fresnel variant '{fresnel_variant}'")
        ct_variant = _text(ct["Variant"]) if "Variant" in ct else ""
        if ct_variant not in _CT_VARIANTS:
            raise AxfFormatError(f"Unsupported Cook-Torrance variant '{ct_variant}'")
        if "Anisotropic" in ct and bool(ct["Anisotropic"][()]):
            raise AxfFormatError("Anisotropic Cook-Torrance lobes are not supported")

        # X-Rite's two decoder generations read the colour table half a texel apart:
        # TabulatedBrdf 1.2 (2016 SDK): texel i at i/N of 90 deg; 1.8 (Pantora 2026): at
        # (i + 0.5)/N. Each reproduces its own files' embedded previews to float precision.
        tab_version = tuple(int(v) for v in np.asarray(tab["Version"][()]).ravel()[:2]) if "Version" in tab else (1, 2)
        table_texel_offset = 0.5 if tab_version >= (1, 8) else 0.0
        table_res = _resource(material, tab["com.xrite.Resources/Data"])[0]
        table = np.asarray(table_res["Data"][()], np.float64)  # [thetaD, thetaH, band or rgb]
        table_colorspec = _text(table_res["ColorSpec"]) if "ColorSpec" in table_res else ""
        if not table_colorspec and table.shape[-1] > 3:
            table_colorspec = "$(COLORSPECS)/spectral"  # untagged multi-band table
        spec_name, spec_group = _colorspec(f, table_colorspec)
        if spec_group is not None and "Wavelengths" in spec_group and table.shape[-1] > 3:
            table_space = SPECTRAL
            wavelengths = np.asarray(spec_group["Wavelengths"][()], np.float64)
            if len(wavelengths) != table.shape[-1]:
                raise AxfFormatError("Spectral colour table does not match its wavelengths")
        elif spec_name == "sRGB,E" and table.shape[-1] == 3:
            table_space = SRGB_E
            wavelengths = None
        else:
            raise AxfFormatError(f"Unsupported colour table colour space '{spec_name or '?'}'")

        # The flake RGB reaches a spectral table through the file's XYZ->spectral basis.
        to_spectral = to_spectral_wl = rgb_e_to_xyz = None
        _, rgb_e = _colorspec(f, "$(COLORSPECS)/sRGB,E")
        if table_space == SPECTRAL and flakes is not None:
            if rgb_e is None or "ToSpectralMatrix" not in rgb_e:
                raise AxfFormatError("Spectral AxF without an sRGB,E to spectral matrix")
            to_spectral = np.asarray(rgb_e["ToSpectralMatrix/Data"][()], np.float64)
            to_spectral_wl = np.asarray(rgb_e["ToSpectralMatrix/Wavelengths"][()], np.float64)
            rgb_e_to_xyz = np.asarray(rgb_e["com.xrite.ColorMatrices/XYZ"][()], np.float64)

        ior, refractive = 1.0, False
        coat_normal, coat_normal_mm = None, (0.0, 0.0)
        coat_res = root["com.xrite.Resources"] if "com.xrite.Resources" in root else None
        if coat_res is not None and any(k not in ("IOR", "Normal") for k in coat_res.keys()):
            extra = sorted(k for k in coat_res.keys() if k not in ("IOR", "Normal"))
            raise AxfFormatError(f"Clear coat resources {extra} are not supported yet")
        if _type(root) == "com.xrite.ClearCoatFilter":
            ior_res = _resource(material, root["com.xrite.Resources/IOR"])[0]
            ior = float(np.asarray(ior_res["Data"][()]).ravel()[0])
            refractive = not bool(root["NoRefraction"][()]) if "NoRefraction" in root else True
            if "UseSolidAngleCompression" in root and bool(root["UseSolidAngleCompression"][()]):
                raise AxfFormatError("Clear coat with solid angle compression is not supported")
            if coat_res is not None and "Normal" in coat_res:
                normal_res = _resource(material, root["com.xrite.Resources/Normal"])[0]
                layout = _text(normal_res["Layout"]) if "Layout" in normal_res else "V U X,Y,Z"
                if layout.replace(",", " ").split() != ["V", "U", "X", "Y", "Z"]:
                    raise AxfFormatError(f"Unsupported clear coat normal layout '{layout}'")
                coat_normal = np.asarray(normal_res["Data"][()], np.float32)  # [V, U, xyz]
                if coat_normal.ndim != 3 or coat_normal.shape[-1] != 3:
                    raise AxfFormatError("Unexpected clear coat normal map shape")
                coat_normal_mm = (float(normal_res["WidthMM"][()]), float(normal_res["HeightMM"][()]))

        out = {
            "name": name,
            "kd": kd,
            "lobes": lobes,  # rows: (coefficient, spread m, F0)
            "ior": ior,
            "refractive": refractive,
            "table": table,  # [thetaD, thetaH, band or rgb], as stored
            "table_space": table_space,
            "table_texel_offset": table_texel_offset,
            "table_version": tab_version,
            "table_colorspec": table_colorspec,
            "wavelengths": wavelengths,
            "to_spectral": to_spectral,
            "to_spectral_wl": to_spectral_wl,
            "rgb_e_to_xyz": rgb_e_to_xyz,
            "coat_normal": coat_normal,  # [V, U, xyz] in (U, V, normal), or None
            "coat_normal_mm": coat_normal_mm,
            "ct_variant": ct_variant,
            "num_theta_f": 0,
            "num_theta_i": 0,
            "lut": np.zeros((0, 0), np.int64),
            "patch_mm": (0.0, 0.0),
            "flakes": None,
            "extra_materials": extra_materials,
        }

        if flakes is not None:
            if _text(flakes["Type"]) != "ThetaFI":
                raise AxfFormatError("Unsupported flake BTF parameterisation")
            out["num_theta_f"] = int(flakes["NumThetaF"][()])
            out["num_theta_i"] = int(flakes["NumThetaI"][()])
            if out["num_theta_i"] < out["num_theta_f"]:
                # X-Rite then synthesises "virtual" thetaI slices by shifting patches.
                raise AxfFormatError("Flake BTFs with virtual thetaI slices are not supported yet")
            out["lut"] = np.asarray(flakes["PatchesLookupTable"][()], np.int64)
            patch_groups = _resource(material, flakes["com.xrite.Resources/Data"])
            parent = patch_groups[0].parent
            out["patch_mm"] = (float(parent["WidthMM"][()]), float(parent["HeightMM"][()]))
            if load_flakes:
                patches = []
                for g in patch_groups:
                    ds = g["Data"]
                    data = ds[()]
                    if ds.attrs.get("axf.datatype") in (b"half", "half"):
                        data = data.view(np.float16)
                    patches.append(np.asarray(data, np.float32))
                out["flakes"] = np.stack(patches)  # (n, V, U, 3), rows in file order
        return out
