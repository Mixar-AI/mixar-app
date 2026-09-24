# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stream encoding and server-side plumbing contracts.

PNG output is parsed back structurally (signature, IHDR, CRCs, inflated
pixel data) because the phone browser is the real decoder and CI has none.
Pairing/token logic and the static-path traversal guard are pinned because
they are the security boundary of the LAN server.
"""

import struct
import zlib

import pytest

from mixar.modules.virtual_camera.core import pairing, stream_encode
from mixar.modules.virtual_camera.core.session import Session


def _parse_png(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks = []
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack_from("!I", data, pos)
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack_from("!I", data, pos + 8 + length)
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, f"bad CRC in {tag}"
        chunks.append((tag, body))
        pos += 12 + length
    return chunks


class TestPNGEncoder:
    def test_roundtrip_pixels_survive(self):
        width, height = 3, 2
        # Bottom-up input (GL order): bottom row red, top row blue.
        bottom = b"\xff\x00\x00\xff" * width
        top = b"\x00\x00\xff\xff" * width
        png = stream_encode.encode_png(bottom + top, width, height)

        chunks = _parse_png(png)
        tags = [t for t, _ in chunks]
        assert tags == [b"IHDR", b"IDAT", b"IEND"]

        ihdr = chunks[0][1]
        w, h, depth, color = struct.unpack_from("!IIBB", ihdr)
        assert (w, h, depth, color) == (width, height, 8, 6)

        raw = zlib.decompress(chunks[1][1])
        stride = 1 + width * 4
        assert len(raw) == stride * height
        # flip_vertical=True: first PNG row (top-down) is the blue input row.
        assert raw[0] == 0  # filter byte
        assert raw[1:5] == b"\x00\x00\xff\xff"
        assert raw[stride + 1:stride + 5] == b"\xff\x00\x00\xff"

    def test_no_flip_preserves_row_order(self):
        width, height = 1, 2
        first = b"\x01\x02\x03\x04"
        second = b"\x05\x06\x07\x08"
        png = stream_encode.encode_png(first + second, width, height,
                                       flip_vertical=False)
        raw = zlib.decompress(_parse_png(png)[1][1])
        assert raw[1:5] == first
        assert raw[6:10] == second

    def test_encode_frame_size_mismatch_raises(self):
        with pytest.raises(ValueError):
            stream_encode.encode_frame(b"\x00" * 10, 4, 4)

    def test_encode_frame_produces_png_or_jpeg(self):
        rgba = b"\x80\x80\x80\xff" * (8 * 8)
        out = stream_encode.encode_frame(rgba, 8, 8)
        is_png = out[:8] == b"\x89PNG\r\n\x1a\n"
        is_jpeg = out[:2] == b"\xff\xd8"
        assert is_png or is_jpeg


class TestPairing:
    def test_token_is_urlsafe_and_random(self):
        tokens = {pairing.generate_token() for _ in range(50)}
        assert len(tokens) == 50
        for token in tokens:
            assert token.isalnum()
            assert len(token) == 16

    def test_pairing_url_shapes(self):
        assert (
            pairing.pairing_url("10.0.0.2", 8143, "tok", tls=True)
            == "https://10.0.0.2:8143/?t=tok"
        )
        assert (
            pairing.pairing_url("10.0.0.2", 8143, "tok", tls=False)
            == "http://10.0.0.2:8143/?t=tok"
        )


class TestStaticPathGuard:
    """The handler resolves paths against the webapp dir; anything that
    normalizes outside of it must 404. Exercised via the same normpath+
    commonpath logic the handler uses (extracted here byte-for-byte)."""

    @staticmethod
    def _is_served(path):
        import os

        from mixar.modules.virtual_camera.core import server as srv

        webapp = srv._WEBAPP_DIR
        if path == "/":
            path = "/index.html"
        rel = os.path.normpath(path.lstrip("/"))
        full = os.path.join(webapp, rel)
        if rel.startswith(".."):
            return False
        if os.path.commonpath([webapp, os.path.abspath(full)]) != webapp:
            return False
        return os.path.isfile(full)

    def test_index_and_assets_served(self):
        assert self._is_served("/")
        assert self._is_served("/index.html")
        assert self._is_served("/app.css")
        assert self._is_served("/js/app.js")

    def test_traversal_rejected(self):
        assert not self._is_served("/../constants.py")
        assert not self._is_served("/../../../../etc/passwd")
        assert not self._is_served("/js/../../core/server.py")

    def test_missing_file_rejected(self):
        assert not self._is_served("/nope.html")


class TestSessionServerContract:
    def test_hello_marks_connected_and_stores_device(self):
        s = Session()
        s.handle_message({"t": "hello", "device": {"ua": "iPhone Safari"}}, now=1.0)
        assert s.connected
        assert s.device_info["ua"] == "iPhone Safari"

    def test_hello_with_junk_device_still_connects(self):
        s = Session()
        s.handle_message({"t": "hello", "device": "junk"}, now=1.0)
        assert s.connected
        assert s.device_info == {}
