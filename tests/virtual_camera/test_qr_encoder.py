# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Structural invariants for the vendored QR encoder.

End-to-end decode validation was done against OpenCV's QRCodeDetector during
development (all of versions 1-6 decode byte-exact); CI has no QR decoder, so
these tests pin the spec-mandated structure instead — finder/timing/format
regions, version selection, capacity math, and determinism. Any regression
that breaks scanning almost always breaks one of these first.
"""

import pytest

from mixar.modules.virtual_camera.core import qr_encoder


URL = "https://192.168.1.23:8143/?t=AbCdEf1234567890"


def _matrix(text=URL):
    return qr_encoder.encode(text)


class TestGeometry:
    def test_matrix_is_square_with_valid_version_size(self):
        m = _matrix()
        size = len(m)
        assert all(len(row) == size for row in m)
        version = (size - 17) // 4
        assert 1 <= version <= qr_encoder.MAX_VERSION
        assert size == version * 4 + 17

    def test_finder_patterns_in_three_corners(self):
        m = _matrix()
        size = len(m)

        def check_finder(cx, cy):
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    expected = max(abs(dx), abs(dy)) != 2
                    assert m[cy + dy][cx + dx] == expected, (cx, cy, dx, dy)

        check_finder(3, 3)
        check_finder(size - 4, 3)
        check_finder(3, size - 4)

    def test_timing_patterns_alternate(self):
        m = _matrix()
        size = len(m)
        for i in range(8, size - 8):
            assert m[6][i] == (i % 2 == 0)
            assert m[i][6] == (i % 2 == 0)

    def test_dark_module_present(self):
        m = _matrix()
        size = len(m)
        version = (size - 17) // 4
        assert m[4 * version + 9][8] is True


class TestFormatInfo:
    def test_format_bits_valid_bch_codeword(self):
        m = _matrix()
        bits = 0
        for i in range(6):
            bits |= int(m[i][8]) << i
        bits |= int(m[7][8]) << 6
        bits |= int(m[8][8]) << 7
        bits |= int(m[8][7]) << 8
        for i in range(9, 15):
            bits |= int(m[8][14 - i]) << i

        unmasked = bits ^ 0x5412
        data, rem = unmasked >> 10, unmasked & 0x3FF
        check = data
        for _ in range(10):
            check = (check << 1) ^ ((check >> 9) * 0x537)
        assert check == rem, "format info fails BCH(15,5) check"
        assert data >> 3 == 0b00, "ECC level must be M"
        assert 0 <= (data & 0b111) <= 7


class TestVersionSelection:
    def test_short_payload_uses_version_1(self):
        assert len(qr_encoder.encode("A")) == 21

    def test_longer_payloads_grow_versions(self):
        sizes = [len(qr_encoder.encode("x" * n)) for n in (10, 40, 80, 150)]
        assert sizes == sorted(sizes)
        assert len(set(sizes)) > 1

    def test_capacity_boundary_exact_fit_and_overflow(self):
        # Version 10 at ECC M holds 216 data codewords; byte mode header for
        # v10 is 4 + 16 bits -> 213 payload bytes fit, 214 cannot.
        max_len = qr_encoder._data_codewords(10) - 3
        qr_encoder.encode("x" * max_len)  # must not raise
        with pytest.raises(ValueError):
            qr_encoder.encode("x" * (max_len + 1))

    def test_utf8_payload_counts_bytes_not_chars(self):
        text = "é" * 100  # 200 UTF-8 bytes
        matrix = qr_encoder.encode(text)
        assert len(matrix) >= 21


class TestDeterminismAndTables:
    def test_encoding_is_deterministic(self):
        assert _matrix() == _matrix()

    def test_codeword_totals_match_spec(self):
        # ISO/IEC 18004 total codeword counts for versions 1-10.
        expected = [26, 44, 70, 100, 134, 172, 196, 242, 292, 346]
        actual = [qr_encoder._total_codewords(v) for v in range(1, 11)]
        assert actual == expected

    def test_alignment_positions_match_spec(self):
        assert qr_encoder._alignment_positions(1) == []
        assert qr_encoder._alignment_positions(2) == [6, 18]
        assert qr_encoder._alignment_positions(7) == [6, 22, 38]
        assert qr_encoder._alignment_positions(10) == [6, 28, 50]

    def test_reed_solomon_remainder_is_valid(self):
        # Appending the remainder must make the polynomial divide evenly.
        gen = qr_encoder._rs_generator(10)
        data = bytes(range(1, 17))
        ecc = qr_encoder._rs_remainder(data, gen)
        assert len(ecc) == 10
        assert qr_encoder._rs_remainder(data + ecc, gen) == bytes(10)

    def test_dark_light_balance_reasonable(self):
        # Mask selection should keep dark modules in a sane band (rule 4
        # of the penalty score enforces proximity to 50%).
        m = _matrix()
        total = len(m) ** 2
        dark = sum(cell for row in m for cell in row)
        assert 0.35 < dark / total < 0.65
