# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Constants for the X-Rite AxF importer (pure Python, no bpy)."""

# Node + ID-property contract with the native AxF Car Paint BSDF
# (intern/cycles/kernel/closure/bsdf_axf_carpaint.h).
NODE_IDNAME = "ShaderNodeBsdfAxFCarPaint"
PROP_TABLE = "axf_table"
PROP_FLAKES = "axf_flakes"
PROP_COAT_NORMAL = "axf_coat_normal"
PARAM_VERSION = 2.0
PARAM_HEADER_TEXELS = 7

# Node + ID-property contract with the native AxF SVBRDF BSDF
# (intern/cycles/kernel/closure/bsdf_axf_svbrdf.h).
SVBRDF_NODE_IDNAME = "ShaderNodeBsdfAxFSvbrdf"
PROP_ATLAS = "axf_atlas"

# Custom properties on the material that record where the data came from.
PROP_SOURCE_NAME = "axf_source_name"
PROP_SOURCE_SHA256 = "axf_source_sha256"
PROP_ARCHIVE = "axf_archive"

# Flake atlas: patches per atlas row.
ATLAS_COLUMNS = 5

# CIE 1931 2-degree colour matching functions and the CIE D65 illuminant,
# 400-700 nm in 10 nm steps (the AxF spectral sampling).
WAVELENGTHS = tuple(range(400, 701, 10))
CMF_X = (0.01431, 0.04351, 0.13438, 0.2839, 0.34828, 0.3362, 0.2908, 0.19536, 0.09564,
         0.03201, 0.0049, 0.0093, 0.06327, 0.1655, 0.2904, 0.4334499, 0.5945, 0.7621,
         0.9163, 1.0263, 1.0622, 1.0026, 0.8544499, 0.6424, 0.4479, 0.2835, 0.1649,
         0.0874, 0.04677, 0.0227, 0.01135916)
CMF_Y = (0.000396, 0.00121, 0.004, 0.0116, 0.023, 0.038, 0.06, 0.09098, 0.13902, 0.20802,
         0.323, 0.503, 0.71, 0.862, 0.954, 0.9949501, 0.995, 0.952, 0.87, 0.757, 0.631,
         0.503, 0.381, 0.265, 0.175, 0.107, 0.061, 0.032, 0.017, 0.00821, 0.004102)
CMF_Z = (0.06785001, 0.2074, 0.6456, 1.3856, 1.74706, 1.77211, 1.6692, 1.28764, 0.8129501,
         0.46518, 0.272, 0.1582, 0.07824999, 0.04216, 0.0203, 0.008749999, 0.0039, 0.0021,
         0.001650001, 0.0011, 0.0008, 0.00034, 0.00019, 0.00004999999, 0.00002, 0.0, 0.0,
         0.0, 0.0, 0.0, 0.0)
D65 = (82.7549, 91.486, 93.4318, 86.6823, 104.865, 117.008, 117.812, 114.861, 115.923,
       108.811, 109.354, 107.802, 104.79, 107.689, 104.405, 104.046, 100.0, 96.3342, 95.788,
       88.6856, 90.0062, 89.5991, 87.6987, 83.2886, 83.6992, 80.0268, 80.2146, 82.2778,
       78.2842, 69.7213, 71.6091)

# CIE XYZ (D65 white) -> linear Rec.709 / sRGB primaries (Blender's scene linear).
XYZ_TO_REC709 = ((3.2404542, -1.5371385, -0.4985314),
                 (-0.9692660, 1.8760108, 0.0415560),
                 (0.0556434, -0.2040259, 1.0572252))
