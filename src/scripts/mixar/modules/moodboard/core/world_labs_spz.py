# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-Python SPZ -> 3DGS PLY decoder.

World Labs (Marble) returns Gaussian splats in Niantic's **SPZ** format, but no
Blender splat importer reads SPZ -- they all want the standard 3DGS
``binary_little_endian`` PLY (graphdeco / INRIA layout). SPZ is just a
gzip-compressed, quantized container of the *same* Gaussian data, so converting
is a lossless repackage: gunzip -> dequantize -> rewrite as PLY.

We own this (instead of pip-installing the native ``spz``/``3dgsconverter``
packages) so it runs in Blender's embedded Python with zero install risk --
``numpy`` is the only dependency and it already ships with Blender.

Format reference: nianticlabs/spz ``src/cc/load-spz.cc`` @ v3.0.0.
Supports the released gzip formats (versions 2 and 3). Version 1 (float16,
never released) and version 4+ (ZSTD) are rejected with a clear error.

Public API
----------
    spz_to_ply(spz_bytes: bytes) -> bytes
"""

import gzip
import logging
import struct

import numpy as np

logger = logging.getLogger(__name__)

# --- SPZ constants (from load-spz.h / load-spz.cc @ v3.0.0) ---
_NGSP_MAGIC = 0x5053474E  # "NGSP" little-endian
_HEADER_SIZE = 16
_MIN_SMALLEST_THREE_VERSION = 3  # v3+ packs rotations as smallest-three (4 bytes)
_MIN_ZSTD_VERSION = 4            # v4+ is ZSTD-compressed (unsupported here)
_FLAG_ANTIALIASED = 0x1
_FLAG_HAS_EXTENSIONS = 0x2
_COLOR_SCALE = 0.15  # colorScale in load-spz.cc
_SQRT1_2 = float(np.sqrt(0.5))


def _dim_for_degree(degree: int) -> int:
    """SH coefficient count per channel for a given SH degree (excl. DC)."""
    return {0: 0, 1: 3, 2: 8, 3: 15, 4: 24}.get(degree, -1)


class SpzError(ValueError):
    """Raised when SPZ data is malformed or in an unsupported format."""


def spz_to_ply(spz_bytes: bytes) -> bytes:
    """Convert SPZ splat bytes into a 3DGS binary_little_endian PLY.

    Parameters
    ----------
    spz_bytes : bytes
        Raw contents of an ``.spz`` file (gzip container, SPZ v2/v3).

    Returns
    -------
    bytes
        A standard 3DGS PLY (graphdeco attribute layout) ready for the KIRI
        3DGS Render importer.

    Raises
    ------
    SpzError
        If the data is not a recognised/supported SPZ stream.
    """
    if len(spz_bytes) < 2:
        raise SpzError("SPZ data too short")

    # v1-3 are gzip-framed (0x1f 0x8b). v4 is raw ZSTD with an NGSP magic header.
    if spz_bytes[0] == 0x1F and spz_bytes[1] == 0x8B:
        try:
            raw = gzip.decompress(spz_bytes)
        except OSError as e:
            raise SpzError(f"Failed to gunzip SPZ: {e}") from e
    elif len(spz_bytes) >= 4 and struct.unpack_from("<I", spz_bytes)[0] == _NGSP_MAGIC:
        raise SpzError(
            "SPZ appears to be version 4+ (ZSTD); only gzip versions 2-3 are "
            "supported. Request a v2/v3 SPZ or add a ZSTD decoder."
        )
    else:
        raise SpzError("Not an SPZ stream (no gzip frame or NGSP magic)")

    header = _parse_header(raw)
    arrays = _read_arrays(raw, header)
    return _build_ply(arrays, header)


def _parse_header(raw: bytes) -> dict:
    """Parse and validate the 16-byte SPZ header from the decompressed buffer."""
    if len(raw) < _HEADER_SIZE:
        raise SpzError("Decompressed SPZ shorter than header")

    magic, version, num_points, sh_degree, frac_bits, flags, _reserved = struct.unpack_from(
        "<III BBBB", raw, 0
    )
    if magic != _NGSP_MAGIC:
        raise SpzError(f"Bad SPZ magic: 0x{magic:08x}")
    if version == 1:
        raise SpzError("SPZ version 1 (float16) is unsupported")
    if version < 2 or version >= _MIN_ZSTD_VERSION:
        raise SpzError(f"Unsupported SPZ version: {version}")

    sh_dim = _dim_for_degree(sh_degree)
    if sh_dim < 0:
        raise SpzError(f"Unsupported SH degree: {sh_degree}")
    if num_points <= 0 or num_points > 30_000_000:
        raise SpzError(f"Invalid SPZ point count: {num_points}")
    if flags & _FLAG_HAS_EXTENSIONS:
        logger.warning("SPZ has extensions; they are ignored by this decoder")

    return {
        "version": version,
        "num_points": num_points,
        "sh_degree": sh_degree,
        "sh_dim": sh_dim,
        "fractional_bits": frac_bits,
        "smallest_three": version >= _MIN_SMALLEST_THREE_VERSION,
        "antialiased": bool(flags & _FLAG_ANTIALIASED),
    }


def _take(raw: bytes, offset: int, count: int) -> tuple:
    """Read ``count`` bytes as a uint8 numpy array; return (array, new_offset)."""
    end = offset + count
    if end > len(raw):
        raise SpzError("SPZ stream truncated (not enough data for arrays)")
    return np.frombuffer(raw, dtype=np.uint8, count=count, offset=offset), end


def _read_arrays(raw: bytes, h: dict) -> dict:
    """Slice the raw uint8 arrays in SPZ order: positions, alphas, colors,
    scales, rotations, sh."""
    n = h["num_points"]
    rot_bytes = 4 if h["smallest_three"] else 3
    off = _HEADER_SIZE

    positions, off = _take(raw, off, n * 9)   # 3 comps * 3 bytes (24-bit fixed)
    alphas, off = _take(raw, off, n)
    colors, off = _take(raw, off, n * 3)
    scales, off = _take(raw, off, n * 3)
    rotations, off = _take(raw, off, n * rot_bytes)
    sh, off = _take(raw, off, n * h["sh_dim"] * 3)

    return {
        "positions": positions, "alphas": alphas, "colors": colors,
        "scales": scales, "rotations": rotations, "sh": sh,
    }


def _decode_positions(positions: np.ndarray, n: int, frac_bits: int) -> np.ndarray:
    """24-bit little-endian signed fixed-point -> float (N, 3)."""
    b = positions.reshape(n, 3, 3).astype(np.int32)
    fixed = b[:, :, 0] | (b[:, :, 1] << 8) | (b[:, :, 2] << 16)
    # Sign-extend bit 23.
    fixed = np.where(fixed & 0x800000, fixed - 0x1000000, fixed)
    return (fixed.astype(np.float32)) / float(1 << frac_bits)


def _decode_rotations(rotations: np.ndarray, n: int, smallest_three: bool) -> np.ndarray:
    """Decode quaternions -> PLY order (w, x, y, z), shape (N, 4).

    SPZ stores quaternion slots as (x, y, z, w) [slot 3 == w]; graphdeco PLY
    wants rot_0=w, rot_1=x, rot_2=y, rot_3=z.
    """
    if smallest_three:
        xyzw = _decode_smallest_three(rotations, n)        # (N,4) as (x,y,z,w)
    else:
        r = rotations.reshape(n, 3).astype(np.float32)
        xyz = r / 127.5 - 1.0
        w = np.sqrt(np.maximum(0.0, 1.0 - np.sum(xyz * xyz, axis=1)))
        xyzw = np.concatenate([xyz, w[:, None]], axis=1)

    # Reorder (x,y,z,w) -> (w,x,y,z)
    return xyzw[:, [3, 0, 1, 2]]


def _decode_smallest_three(rotations: np.ndarray, n: int) -> np.ndarray:
    """Smallest-three quaternion decode -> (N, 4) as (x, y, z, w)."""
    r = rotations.reshape(n, 4).astype(np.uint32)
    comp = r[:, 0] | (r[:, 1] << 8) | (r[:, 2] << 16) | (r[:, 3] << 24)
    i_largest = (comp >> 30).astype(np.int64)

    quat = np.zeros((n, 4), dtype=np.float32)
    sum_sq = np.zeros(n, dtype=np.float32)

    # Fields are consumed from the LSB upward (k=0,1,2) and assigned to the
    # non-largest slots in descending index order (3,2,1,0 minus i_largest).
    slot_order = {
        0: (3, 2, 1),
        1: (3, 2, 0),
        2: (3, 1, 0),
        3: (2, 1, 0),
    }
    for k in range(3):
        field = (comp >> (10 * k)) & 0x3FF
        mag = (field & 0x1FF).astype(np.float32)
        neg = ((field >> 9) & 0x1).astype(bool)
        val = _SQRT1_2 * mag / 511.0
        val = np.where(neg, -val, val).astype(np.float32)
        for largest in range(4):
            sel = i_largest == largest
            if not np.any(sel):
                continue
            slot = slot_order[largest][k]
            quat[sel, slot] = val[sel]
            sum_sq[sel] += val[sel] * val[sel]

    largest_val = np.sqrt(np.maximum(0.0, 1.0 - sum_sq)).astype(np.float32)
    quat[np.arange(n), i_largest] = largest_val
    return quat


def _build_ply(arrays: dict, h: dict) -> bytes:
    """Dequantize all fields and serialise to a 3DGS binary PLY."""
    n = h["num_points"]
    sh_dim = h["sh_dim"]

    positions = _decode_positions(arrays["positions"], n, h["fractional_bits"])

    # scales are log-encoded; PLY scale_* store log scale directly.
    scales = arrays["scales"].reshape(n, 3).astype(np.float32) / 16.0 - 10.0

    rotations = _decode_rotations(arrays["rotations"], n, h["smallest_three"])

    # Coordinate conversion: SPZ stores splats in RUB (Right-Up-Back, Y-up),
    # but the standard 3DGS PLY consumed by KIRI / viewers is RDF (Right-Down-
    # Front, Y-down, Z-forward) — this is what Niantic's own save_splat_to_ply
    # emits. RUB->RDF is a 180-deg rotation about X: negate Y,Z on positions and
    # negate the y,z components of each quaternion. (DC colour is direction-
    # independent; SH rest coeffs would need parity sign-flips for view-dependent
    # colour, but World Labs 500k splats are shDegree=0, so there are none.)
    positions[:, 1] *= -1.0
    positions[:, 2] *= -1.0
    rotations[:, 2] *= -1.0  # quaternion y
    rotations[:, 3] *= -1.0  # quaternion z

    # opacity: PLY stores the pre-sigmoid logit. invSigmoid(a/255).
    a = arrays["alphas"].astype(np.float32) / 255.0
    a = np.clip(a, 1e-6, 1.0 - 1e-6)
    opacity = np.log(a / (1.0 - a)).astype(np.float32)[:, None]

    # DC color -> SH DC coefficient.
    colors = arrays["colors"].reshape(n, 3).astype(np.float32)
    f_dc = ((colors / 255.0) - 0.5) / _COLOR_SCALE

    normals = np.zeros((n, 3), dtype=np.float32)

    columns = [positions, normals, f_dc]
    prop_names = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]

    if sh_dim > 0:
        # SPZ sh: (N, sh_dim, 3) coeff-major [R,G,B]. PLY f_rest is channel-major
        # [R0..R(D-1), G0.., B0..] -> transpose to (N, 3, sh_dim) then flatten.
        sh = arrays["sh"].reshape(n, sh_dim, 3).astype(np.float32)
        sh = (sh - 128.0) / 128.0
        f_rest = np.transpose(sh, (0, 2, 1)).reshape(n, sh_dim * 3)
        columns.append(f_rest)
        prop_names += [f"f_rest_{i}" for i in range(sh_dim * 3)]
    else:
        # No SH in the SPZ, but the KIRI importer requires f_rest_* attributes.
        # Emit a degree-1-shaped zero block so the PLY is always KIRI-importable
        # (zero rest coefficients == no view-dependent colour, visually fine).
        f_rest = np.zeros((n, 9), dtype=np.float32)
        columns.append(f_rest)
        prop_names += [f"f_rest_{i}" for i in range(9)]

    columns += [opacity, scales, rotations]
    prop_names += ["opacity", "scale_0", "scale_1", "scale_2",
                   "rot_0", "rot_1", "rot_2", "rot_3"]

    data = np.concatenate(columns, axis=1).astype("<f4", copy=False)

    header_lines = [
        "ply",
        "format binary_little_endian 1.0",
        f"element vertex {n}",
    ]
    header_lines += [f"property float {name}" for name in prop_names]
    header_lines.append("end_header\n")
    header = ("\n".join(header_lines)).encode("ascii")

    return header + data.tobytes(order="C")
