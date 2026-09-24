# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-Python QR encoder (byte mode, ECC level M, versions 1-10).

Dependency-free so the overlay build needs no new packages. Encodes the short
pairing URLs shown in the Virtual Camera panel; the matrix is returned as a
list of rows of booleans (True = dark module) for the caller to rasterize.

Implementation follows the QR model 2 spec (ISO/IEC 18004): byte-mode
segments, Reed-Solomon ECC over GF(256), block interleaving, penalty-scored
mask selection.
"""

from __future__ import annotations

MAX_VERSION = 10

# ECC level M: codeword tables for versions 1..10.
_ECC_PER_BLOCK = (10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_NUM_BLOCKS = (1, 1, 1, 2, 2, 4, 4, 4, 5, 5)

_FORMAT_ECC_BITS_M = 0b00  # ECC level indicator for M


def _raw_data_modules(version: int) -> int:
    result = (16 * version + 128) * version + 64
    if version >= 2:
        numalign = version // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if version >= 7:
            result -= 36
    return result


def _total_codewords(version: int) -> int:
    return _raw_data_modules(version) // 8


def _data_codewords(version: int) -> int:
    return _total_codewords(version) - _ECC_PER_BLOCK[version - 1] * _NUM_BLOCKS[version - 1]


def _alignment_positions(version: int) -> list[int]:
    if version == 1:
        return []
    numalign = version // 7 + 2
    step = (version * 4 + numalign * 2 + 1) // (numalign * 2 - 2) * 2
    result = [6]
    pos = version * 4 + 10
    for _ in range(numalign - 1):
        result.insert(1, pos)
        pos -= step
    return result


# ---------------------------------------------------------------------------
# Reed-Solomon over GF(256), reducing polynomial 0x11D
# ---------------------------------------------------------------------------

def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_generator(degree: int) -> list[int]:
    """Coefficients of prod (x - a^i), highest power first, monic lead dropped."""
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: bytes, divisor: list[int]) -> bytes:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return bytes(result)


# ---------------------------------------------------------------------------
# Bit assembly
# ---------------------------------------------------------------------------

class _BitBuffer:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def append(self, value: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            self.bits.append((value >> i) & 1)


def _build_codewords(payload: bytes, version: int) -> bytes:
    capacity_bits = _data_codewords(version) * 8
    bb = _BitBuffer()
    bb.append(0b0100, 4)                       # byte mode
    bb.append(len(payload), 16 if version >= 10 else 8)
    for b in payload:
        bb.append(b, 8)
    if len(bb.bits) > capacity_bits:
        raise ValueError("payload does not fit selected version")
    bb.append(0, min(4, capacity_bits - len(bb.bits)))   # terminator
    bb.append(0, (8 - len(bb.bits) % 8) % 8)             # byte align
    pad = 0xEC
    while len(bb.bits) < capacity_bits:
        bb.append(pad, 8)
        pad = 0x11 if pad == 0xEC else 0xEC

    data = bytearray()
    for i in range(0, len(bb.bits), 8):
        byte = 0
        for bit in bb.bits[i:i + 8]:
            byte = (byte << 1) | bit
        data.append(byte)
    return _interleave(bytes(data), version)


def _interleave(data: bytes, version: int) -> bytes:
    numblocks = _NUM_BLOCKS[version - 1]
    ecclen = _ECC_PER_BLOCK[version - 1]
    total = _total_codewords(version)
    numshort = numblocks - total % numblocks
    shortlen = total // numblocks - ecclen  # data codewords in a short block

    blocks: list[bytes] = []
    eccs: list[bytes] = []
    gen = _rs_generator(ecclen)
    k = 0
    for i in range(numblocks):
        datlen = shortlen + (0 if i < numshort else 1)
        block = data[k:k + datlen]
        k += datlen
        blocks.append(block)
        eccs.append(_rs_remainder(block, gen))

    out = bytearray()
    maxlen = max(len(b) for b in blocks)
    for i in range(maxlen):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ecclen):
        for e in eccs:
            out.append(e[i])
    return bytes(out)


# ---------------------------------------------------------------------------
# Matrix construction
# ---------------------------------------------------------------------------

def _make_function_modules(version: int):
    size = version * 4 + 17
    modules = [[False] * size for _ in range(size)]
    isfunc = [[False] * size for _ in range(size)]

    def set_module(x: int, y: int, dark: bool) -> None:
        modules[y][x] = dark
        isfunc[y][x] = True

    # Timing patterns
    for i in range(size):
        set_module(6, i, i % 2 == 0)
        set_module(i, 6, i % 2 == 0)

    # Finder patterns + separators
    def draw_finder(cx: int, cy: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    dist = max(abs(dx), abs(dy))
                    set_module(x, y, dist != 2 and dist != 4)

    draw_finder(3, 3)
    draw_finder(size - 4, 3)
    draw_finder(3, size - 4)

    # Alignment patterns (skip the three finder corners)
    align = _alignment_positions(version)
    n = len(align)
    for i in range(n):
        for j in range(n):
            if (i == 0 and j == 0) or (i == 0 and j == n - 1) or (i == n - 1 and j == 0):
                continue
            cx, cy = align[i], align[j]
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    set_module(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    # Reserve format info areas (filled later per mask)
    for i in range(9):
        isfunc[8][i] = isfunc[i][8] = True
    for i in range(8):
        isfunc[8][size - 1 - i] = True
        isfunc[size - 1 - i][8] = True
    modules[size - 8][8] = True  # dark module
    isfunc[size - 8][8] = True

    # Version info (v >= 7)
    if version >= 7:
        rem = version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = version << 12 | rem
        for i in range(18):
            bit = (bits >> i) & 1
            a, b = size - 11 + i % 3, i // 3
            set_module(a, b, bit == 1)
            set_module(b, a, bit == 1)

    return modules, isfunc


def _draw_codewords(modules, isfunc, codewords: bytes) -> None:
    size = len(modules)
    i = 0  # bit index
    total_bits = len(codewords) * 8
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = (size - 1 - vert) if upward else vert
                if not isfunc[y][x]:
                    dark = False
                    if i < total_bits:
                        dark = ((codewords[i >> 3] >> (7 - (i & 7))) & 1) != 0
                        i += 1
                    modules[y][x] = dark
        right -= 2


_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def _apply_mask(modules, isfunc, mask: int) -> None:
    size = len(modules)
    fn = _MASKS[mask]
    for y in range(size):
        for x in range(size):
            if not isfunc[y][x] and fn(x, y):
                modules[y][x] = not modules[y][x]


def _draw_format_bits(modules, mask: int) -> None:
    size = len(modules)
    data = _FORMAT_ECC_BITS_M << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    bits = (data << 10 | rem) ^ 0x5412

    for i in range(6):
        modules[i][8] = ((bits >> i) & 1) != 0
    modules[7][8] = ((bits >> 6) & 1) != 0
    modules[8][8] = ((bits >> 7) & 1) != 0
    modules[8][7] = ((bits >> 8) & 1) != 0
    for i in range(9, 15):
        modules[8][14 - i] = ((bits >> i) & 1) != 0

    for i in range(8):
        modules[8][size - 1 - i] = ((bits >> i) & 1) != 0
    for i in range(8, 15):
        modules[size - 15 + i][8] = ((bits >> i) & 1) != 0
    modules[size - 8][8] = True


def _penalty(modules) -> int:
    size = len(modules)
    score = 0

    def runs_penalty(line) -> int:
        s, run, prev = 0, 0, None
        finder = 0
        for cell in line:
            if cell == prev:
                run += 1
            else:
                if run >= 5:
                    s += 3 + (run - 5)
                run, prev = 1, cell
        if run >= 5:
            s += 3 + (run - 5)
        # Rule 3: finder-like patterns 1:1:3:1:1 with 4-module light flank
        pat_a = [True, False, True, True, True, False, True, False, False, False, False]
        pat_b = pat_a[::-1]
        as_list = list(line)
        for i in range(len(as_list) - 10):
            window = as_list[i:i + 11]
            if window == pat_a or window == pat_b:
                finder += 40
        return s + finder

    for y in range(size):
        score += runs_penalty(modules[y])
    for x in range(size):
        score += runs_penalty([modules[y][x] for y in range(size)])

    for y in range(size - 1):
        for x in range(size - 1):
            c = modules[y][x]
            if c == modules[y][x + 1] == modules[y + 1][x] == modules[y + 1][x + 1]:
                score += 3

    dark = sum(cell for row in modules for cell in row)
    total = size * size
    k = (abs(dark * 20 - total * 10) + total - 1) // total
    score += 10 * k
    return score


def encode(text: str) -> list[list[bool]]:
    """Encode *text* (UTF-8, byte mode, ECC M) → matrix of booleans."""
    payload = text.encode("utf-8")
    version = None
    for v in range(1, MAX_VERSION + 1):
        header = 4 + (16 if v >= 10 else 8)
        if header + 8 * len(payload) <= _data_codewords(v) * 8:
            version = v
            break
    if version is None:
        raise ValueError(f"payload too long for version {MAX_VERSION}")

    codewords = _build_codewords(payload, version)
    modules, isfunc = _make_function_modules(version)
    _draw_codewords(modules, isfunc, codewords)

    best_mask, best_score = 0, None
    for mask in range(8):
        _apply_mask(modules, isfunc, mask)
        _draw_format_bits(modules, mask)
        score = _penalty(modules)
        if best_score is None or score < best_score:
            best_mask, best_score = mask, score
        _apply_mask(modules, isfunc, mask)  # XOR mask is its own inverse

    _apply_mask(modules, isfunc, best_mask)
    _draw_format_bits(modules, best_mask)
    return modules
