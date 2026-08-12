# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Round-trip tests for the World Labs SPZ -> 3DGS PLY decoder.

There is no public SPZ encoder in Blender's embedded Python, so these tests
build a synthetic SPZ buffer using the inverse of the documented quantization
formulas, decode it, and assert the recovered values match within quantization
tolerance. This validates header parsing, array ordering, and every
dequantization path against the format spec
(nianticlabs/spz load-spz.cc @ v3.0.0).

NOTE: round-trip against our own encoder cannot catch a shared misunderstanding
of the real format -- validation against a genuine World Labs SPZ sample is
still required before shipping.

Lives at repo-root ``tests/`` (not beside the module) because the moodboard
package tree omits ``__init__.py`` in places (synthetic packages built by the
bootstrap at runtime), so an in-package test cannot import cleanly under pytest.
The decoder has no bpy/mixar imports, so it is loaded directly by file path.
"""

import gzip
import importlib.util
import pathlib
import struct

import numpy as np
import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SPZ_PATH = (
    _REPO_ROOT
    / "src/scripts/mixar/modules/moodboard/core/world_labs_spz.py"
)
_spec = importlib.util.spec_from_file_location("world_labs_spz", _SPZ_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
spz_to_ply = _mod.spz_to_ply
SpzError = _mod.SpzError
_rotate_sh_rub_to_rdf = _mod._rotate_sh_rub_to_rdf

_NGSP_MAGIC = 0x5053474E
_COLOR_SCALE = 0.15


def _pack_fixed24(values, frac_bits):
    """Float coords -> little-endian signed 24-bit bytes."""
    out = bytearray()
    scale = 1 << frac_bits
    for v in values:
        fixed = int(round(v * scale)) & 0xFFFFFF
        out += bytes((fixed & 0xFF, (fixed >> 8) & 0xFF, (fixed >> 16) & 0xFF))
    return bytes(out)


def _make_spz_v2(positions, scales_log, colors_dc, alphas01, quats_xyz, sh=None,
                 sh_degree=0, frac_bits=12):
    """Build a synthetic SPZ v2 (first-three rotations) buffer (gzip-framed)."""
    n = len(positions)
    header = struct.pack(
        "<III BBBB", _NGSP_MAGIC, 2, n, sh_degree, frac_bits, 0, 0
    )

    pos_bytes = b"".join(_pack_fixed24(p, frac_bits) for p in positions)
    alpha_bytes = bytes(int(round(a * 255)) & 0xFF for a in alphas01)
    color_bytes = bytes(
        int(round(c * (_COLOR_SCALE * 255) + 0.5 * 255)) & 0xFF
        for col in colors_dc for c in col
    )
    scale_bytes = bytes(
        int(round((s + 10.0) * 16.0)) & 0xFF for sc in scales_log for s in sc
    )
    # v2 first-three rotation: byte = (comp + 1) * 127.5
    rot_bytes = bytes(
        int(round((q + 1.0) * 127.5)) & 0xFF for quat in quats_xyz for q in quat
    )
    sh_bytes = b""
    if sh is not None:
        sh_bytes = bytes(int(v) & 0xFF for v in np.asarray(sh).ravel())

    raw = header + pos_bytes + alpha_bytes + color_bytes + scale_bytes + rot_bytes + sh_bytes
    return gzip.compress(raw)


def _parse_ply(ply_bytes):
    """Minimal 3DGS binary PLY reader -> (prop_names, np.ndarray (N, P))."""
    end = ply_bytes.index(b"end_header\n") + len(b"end_header\n")
    header = ply_bytes[:end].decode("ascii")
    names, count = [], 0
    for line in header.splitlines():
        if line.startswith("element vertex"):
            count = int(line.split()[-1])
        elif line.startswith("property float"):
            names.append(line.split()[-1])
    data = np.frombuffer(ply_bytes[end:], dtype="<f4").reshape(count, len(names))
    return names, data


def test_decode_v2_degree0_roundtrip():
    positions = [(1.5, -2.25, 0.0), (10.0, 0.5, -7.0)]
    scales_log = [(-3.0, -3.5, -4.0), (0.0, -1.0, -2.0)]
    colors_dc = [(0.2, -0.1, 0.05), (0.0, 0.3, -0.3)]
    alphas01 = [0.7, 0.3]
    quats_xyz = [(0.1, 0.2, 0.3), (0.0, 0.0, 0.0)]  # w derived

    spz = _make_spz_v2(positions, scales_log, colors_dc, alphas01, quats_xyz)
    names, data = _parse_ply(spz_to_ply(spz))

    assert data.shape[0] == 2
    # degree 0 -> zero-padded f_rest block (9 cols) for KIRI compatibility
    assert "f_rest_0" in names and "f_rest_8" in names and "f_rest_9" not in names
    idx = {nm: i for i, nm in enumerate(names)}
    assert np.allclose([data[:, idx[f"f_rest_{i}"]] for i in range(9)], 0.0)

    # Decoder converts RUB -> RDF (standard PLY): Y and Z are negated.
    expected_pos = np.array(positions, dtype=float) * np.array([1.0, -1.0, -1.0])
    np.testing.assert_allclose(
        data[:, [idx["x"], idx["y"], idx["z"]]], expected_pos, atol=1e-3
    )
    np.testing.assert_allclose(
        data[:, [idx["scale_0"], idx["scale_1"], idx["scale_2"]]],
        scales_log, atol=0.05,
    )
    np.testing.assert_allclose(
        data[:, [idx["f_dc_0"], idx["f_dc_1"], idx["f_dc_2"]]],
        colors_dc, atol=0.05,
    )
    expected_op = np.log(np.array(alphas01) / (1 - np.array(alphas01)))
    np.testing.assert_allclose(data[:, idx["opacity"]], expected_op, atol=0.05)
    assert np.allclose(data[:, [idx["nx"], idx["ny"], idx["nz"]]], 0.0)


def test_decode_rotation_order_and_norm():
    # Quaternion (x,y,z)=(0.1,0.2,0.3) -> w=sqrt(1-0.14). PLY order is (w,x,y,z).
    spz = _make_spz_v2(
        [(0.0, 0.0, 0.0)], [(-3.0, -3.0, -3.0)], [(0.0, 0.0, 0.0)],
        [0.5], [(0.1, 0.2, 0.3)],
    )
    names, data = _parse_ply(spz_to_ply(spz))
    idx = {nm: i for i, nm in enumerate(names)}
    w = data[0, idx["rot_0"]]
    x, y, z = (data[0, idx["rot_1"]], data[0, idx["rot_2"]], data[0, idx["rot_3"]])
    # RUB->RDF negates quaternion y,z: expect (w, 0.1, -0.2, -0.3).
    assert abs(x - 0.1) < 0.02 and abs(y + 0.2) < 0.02 and abs(z + 0.3) < 0.02
    assert abs(w - np.sqrt(1 - 0.14)) < 0.02
    assert abs((w * w + x * x + y * y + z * z) - 1.0) < 0.05  # normalized


def test_decode_degree1_sh_channel_major():
    # sh_dim=3 for degree 1; SPZ sh is (N, 3coeff, 3channel) -> 9 bytes/point.
    # Byte 128 -> 0.0 after (b-128)/128. Layout per point:
    # coeff0[R,G,B], coeff1[R,G,B], coeff2[R,G,B]
    sh = [[128 + 10, 128 + 20, 128 + 30,
           128 + 40, 128 + 50, 128 + 60,
           128 + 70, 128 + 80, 128 + 90]]
    spz = _make_spz_v2(
        [(0.0, 0.0, 0.0)], [(-3.0, -3.0, -3.0)], [(0.0, 0.0, 0.0)],
        [0.5], [(0.0, 0.0, 0.0)], sh=sh, sh_degree=1,
    )
    names, data = _parse_ply(spz_to_ply(spz))
    idx = {nm: i for i, nm in enumerate(names)}
    assert "f_rest_8" in names and "f_rest_9" not in names  # exactly 9 coeffs

    # PLY f_rest is channel-major: [R0,R1,R2, G0,G1,G2, B0,B1,B2]
    # RUB -> RDF negates the l=1 coefficients [Y, Z] and keeps X.
    expected = np.array([-10, -40, 70, -20, -50, 80, -30, -60, 90]) / 128.0
    got = np.array([data[0, idx[f"f_rest_{i}"]] for i in range(9)])
    np.testing.assert_allclose(got, expected, atol=1e-4)


def test_rub_to_rdf_rotates_all_supported_sh_bands():
    """Pin Niantic's canonical degree 1-4 RUB -> RDF ``flipSh`` table."""
    coeffs = np.arange(1, 25, dtype=np.float32).reshape(1, 24, 1)
    rgb = np.repeat(coeffs, 3, axis=2)
    signs = np.array([
        -1, -1, 1,
        -1, 1, 1, -1, 1,
        -1, 1, -1, -1, 1, -1, 1,
        -1, 1, -1, 1, 1, -1, 1, -1, -1,
    ], dtype=np.float32)

    rotated = _rotate_sh_rub_to_rdf(rgb)

    np.testing.assert_array_equal(rotated[0, :, 0], np.arange(1, 25) * signs)
    np.testing.assert_array_equal(rotated[0, :, 1], rotated[0, :, 0])
    np.testing.assert_array_equal(rotated[0, :, 2], rotated[0, :, 0])


def test_rejects_zstd_v4():
    # NGSP magic with no gzip frame -> looks like v4 (ZSTD), unsupported.
    fake_v4 = struct.pack("<I", _NGSP_MAGIC) + b"\x00" * 32
    with pytest.raises(SpzError, match="version 4"):
        spz_to_ply(fake_v4)


def test_rejects_garbage():
    with pytest.raises(SpzError):
        spz_to_ply(b"not an spz file at all")
