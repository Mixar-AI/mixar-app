# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The native resting pill's working-state label must not shift as dots animate.

The live painter is C++ ``agent_ui_draw_status_pill`` (the Python
``AGENT_BUBBLE_HT_header`` path is currently unreachable). It left-aligns
``status + field + · preview``, so a variable-width field slides the preview.
The field is three slots of U+00B7 (MIDDLE DOT) or U+0020 (SPACE). This file
reads those advances out of the shipped Manrope.ttf via ``cmap`` + ``hmtx``
— the same face ``BLF_default`` uses.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANROPE = ROOT / "src" / "release" / "datafiles" / "fonts" / "Manrope.ttf"
DRAW_CC = (
    ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble" / "agent_ui_draw.cc"
)

SPACE = 0x0020
PERIOD = 0x002E
MIDDLE_DOT = 0x00B7
FIGURE_SPACE = 0x2007
PUNCTUATION_SPACE = 0x2008

SLOTS = 3


class _TTF:
    """Enough of a TrueType reader for cmap glyph ids and hmtx advances."""

    def __init__(self, data: bytes):
        self._d = data
        self._tables = self._read_tables()
        self.units_per_em = self._u16(self._tables[b"head"] + 18)
        self._number_of_h_metrics = self._u16(self._tables[b"hhea"] + 34)
        self._hmtx = self._tables[b"hmtx"]
        self._cmap = self._parse_cmap()

    def _u16(self, off: int) -> int:
        return struct.unpack_from(">H", self._d, off)[0]

    def _i16(self, off: int) -> int:
        return struct.unpack_from(">h", self._d, off)[0]

    def _u32(self, off: int) -> int:
        return struct.unpack_from(">I", self._d, off)[0]

    def _read_tables(self) -> dict[bytes, int]:
        num = self._u16(4)
        tables: dict[bytes, int] = {}
        off = 12
        for _ in range(num):
            tag = self._d[off : off + 4]
            tables[tag] = self._u32(off + 8)
            off += 16
        return tables

    def _parse_cmap(self) -> dict[int, int]:
        cmap = self._tables[b"cmap"]
        num = self._u16(cmap + 2)
        subtables: list[tuple[int, int, int]] = []
        for i in range(num):
            rec = cmap + 4 + i * 8
            plat, enc, suboff = struct.unpack_from(">HHI", self._d, rec)
            fmt = self._u16(cmap + suboff)
            subtables.append((plat, enc, cmap + suboff, fmt))
        mapping: dict[int, int] = {}
        fmt12 = next((s for s in subtables if s[3] == 12), None)
        fmt4 = next((s for s in subtables if s[3] == 4), None)
        if fmt12 is not None:
            mapping.update(self._cmap_format12(fmt12[2]))
        elif fmt4 is not None:
            mapping.update(self._cmap_format4(fmt4[2]))
        return mapping

    def _cmap_format4(self, sub: int) -> dict[int, int]:
        seg_count = self._u16(sub + 6) // 2
        end_off = sub + 14
        start_off = end_off + 2 * seg_count + 2
        delta_off = start_off + 2 * seg_count
        range_off = delta_off + 2 * seg_count
        mapping: dict[int, int] = {}
        for i in range(seg_count):
            start = self._u16(start_off + 2 * i)
            end = self._u16(end_off + 2 * i)
            id_delta = self._i16(delta_off + 2 * i)
            id_range = self._u16(range_off + 2 * i)
            for cp in range(start, end + 1):
                if id_range == 0:
                    gid = (cp + id_delta) & 0xFFFF
                else:
                    glyph_addr = range_off + 2 * i + id_range + 2 * (cp - start)
                    gid = self._u16(glyph_addr)
                    if gid != 0:
                        gid = (gid + id_delta) & 0xFFFF
                mapping[cp] = gid
        return mapping

    def _cmap_format12(self, sub: int) -> dict[int, int]:
        n_groups = self._u32(sub + 12)
        mapping: dict[int, int] = {}
        g_off = sub + 16
        for i in range(n_groups):
            start_cp, end_cp, start_gid = struct.unpack_from(">III", self._d, g_off + i * 12)
            for cp in range(start_cp, end_cp + 1):
                mapping[cp] = start_gid + (cp - start_cp)
        return mapping

    def glyph_id(self, cp: int) -> int | None:
        gid = self._cmap.get(cp)
        if gid is None or gid == 0:
            return None
        return gid

    def advance(self, gid: int) -> int:
        if gid < self._number_of_h_metrics:
            return self._u16(self._hmtx + gid * 4)
        return self._u16(self._hmtx + (self._number_of_h_metrics - 1) * 4)

    def advance_for(self, cp: int) -> int | None:
        gid = self.glyph_id(cp)
        if gid is None:
            return None
        return self.advance(gid)


@pytest.fixture(scope="module")
def manrope() -> _TTF:
    if not MANROPE.is_file():
        pytest.skip(f"Manrope.ttf not present at {MANROPE}")
    return _TTF(MANROPE.read_bytes())


def _activity_field(dot_count: int) -> str:
    """The 3-slot field ``agent_ui_draw_status_pill`` concatenates into the label."""
    chars = []
    for i in range(SLOTS):
        chars.append("\u00b7" if i < dot_count else " ")
    return "".join(chars)


def _summed_advance(font: _TTF, text: str) -> int:
    total = 0
    for ch in text:
        adv = font.advance_for(ord(ch))
        assert adv is not None, f"U+{ord(ch):04X} missing from Manrope cmap"
        total += adv
    return total


def test_manrope_ships_middle_dot_and_space(manrope: _TTF) -> None:
    assert manrope.glyph_id(MIDDLE_DOT) is not None
    assert manrope.glyph_id(SPACE) is not None


def test_middle_dot_and_space_share_the_same_advance(manrope: _TTF) -> None:
    """Equal advances are what keep a 3-slot mix of the two glyphs fixed-width."""
    assert manrope.advance_for(MIDDLE_DOT) == manrope.advance_for(SPACE)


def test_four_activity_field_steps_have_equal_summed_advance(manrope: _TTF) -> None:
    widths = [_summed_advance(manrope, _activity_field(step)) for step in range(SLOTS + 1)]
    assert len(set(widths)) == 1
    assert widths[0] == SLOTS * manrope.advance_for(SPACE)


def test_period_does_not_match_space_advance(manrope: _TTF) -> None:
    """A '.' in the field would still breathe: it is wider than space in Manrope."""
    period = manrope.advance_for(PERIOD)
    space = manrope.advance_for(SPACE)
    assert period is not None
    assert period != space


def test_figure_and_punctuation_space_are_absent_from_manrope(manrope: _TTF) -> None:
    """Those pad characters are not in this face; using them would substitute."""
    assert manrope.glyph_id(FIGURE_SPACE) is None
    assert manrope.glyph_id(PUNCTUATION_SPACE) is None


def test_native_painter_builds_the_fixed_middle_dot_field() -> None:
    src = DRAW_CC.read_text(encoding="utf-8")
    start = src.index("void agent_ui_draw_status_pill")
    body = src[start : src.index("void agent_ui_draw_island", start)]
    elongated = body[body.index("if (w > h * 4.0f)") :]
    assert "char dots[3 * 2 + 1]" in elongated
    assert "*d++ = '\\xc2'" in elongated
    assert "*d++ = '\\xb7'" in elongated
    assert "dots[i] = '.'" not in elongated
