# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""RFC 6455 codec tests: handshake key, framing round-trips, protocol errors.

The virtual-camera server terminates real Safari/Chrome WebSocket clients
with this codec, so the tests pin the spec-visible behavior: the RFC's own
handshake vector, masked client frames, fragmentation, interleaved control
frames, and every reject path that must drop a hostile connection.
"""

import struct

import pytest

from mixar.modules.virtual_camera.core import ws_codec
from mixar.modules.virtual_camera.core.ws_codec import (
    FrameReader,
    OP_BINARY,
    OP_CLOSE,
    OP_CONT,
    OP_PING,
    OP_TEXT,
    WSProtocolError,
    accept_key,
    encode_close,
    encode_frame,
)


def _mask_frame(opcode, payload, *, fin=True, mask=b"\x11\x22\x33\x44",
                rsv=0):
    """Build a client-to-server (masked) frame byte-exactly."""
    head = bytearray()
    head.append((0x80 if fin else 0x00) | (rsv << 4) | opcode)
    n = len(payload)
    if n <= 125:
        head.append(0x80 | n)
    elif n <= 0xFFFF:
        head.append(0x80 | 126)
        head += struct.pack("!H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack("!Q", n)
    head += mask
    body = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    return bytes(head) + body


def _drain(reader):
    return list(reader.messages())


class TestHandshake:
    def test_rfc6455_reference_vector(self):
        # The exact example from RFC 6455 §1.3.
        assert (
            accept_key("dGhlIHNhbXBsZSBub25jZQ==")
            == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        )


class TestEncode:
    def test_small_text_frame_is_unmasked_with_fin(self):
        frame = encode_frame(OP_TEXT, b"hi")
        assert frame == b"\x81\x02hi"

    def test_medium_frame_uses_16bit_length(self):
        payload = b"x" * 300
        frame = encode_frame(OP_BINARY, payload)
        assert frame[:4] == bytes([0x82, 126]) + struct.pack("!H", 300)

    def test_large_frame_uses_64bit_length(self):
        payload = b"x" * 70000
        frame = encode_frame(OP_BINARY, payload)
        assert frame[:10] == bytes([0x82, 127]) + struct.pack("!Q", 70000)

    def test_control_frame_payload_over_125_rejected(self):
        with pytest.raises(ValueError):
            encode_frame(OP_PING, b"x" * 126)

    def test_close_frame_carries_code_and_reason(self):
        frame = encode_close(4000, "replaced")
        assert frame[0] == 0x80 | OP_CLOSE
        assert struct.pack("!H", 4000) + b"replaced" == frame[2:]


class TestReader:
    def test_masked_text_roundtrip(self):
        reader = FrameReader()
        reader.feed(_mask_frame(OP_TEXT, b'{"t":"ctl"}'))
        assert _drain(reader) == [(OP_TEXT, b'{"t":"ctl"}')]

    def test_partial_feed_then_completion(self):
        frame = _mask_frame(OP_TEXT, b"hello world")
        reader = FrameReader()
        reader.feed(frame[:5])
        assert _drain(reader) == []
        reader.feed(frame[5:])
        assert _drain(reader) == [(OP_TEXT, b"hello world")]

    def test_fragmented_message_reassembled(self):
        reader = FrameReader()
        reader.feed(_mask_frame(OP_TEXT, b"hel", fin=False))
        reader.feed(_mask_frame(OP_CONT, b"lo", fin=True))
        assert _drain(reader) == [(OP_TEXT, b"hello")]

    def test_control_frame_interleaved_with_fragments(self):
        reader = FrameReader()
        reader.feed(_mask_frame(OP_TEXT, b"ab", fin=False))
        reader.feed(_mask_frame(OP_PING, b"p"))
        reader.feed(_mask_frame(OP_CONT, b"cd", fin=True))
        assert _drain(reader) == [(OP_PING, b"p"), (OP_TEXT, b"abcd")]

    def test_16bit_length_client_frame(self):
        payload = bytes(range(256)) * 2
        reader = FrameReader()
        reader.feed(_mask_frame(OP_BINARY, payload))
        assert _drain(reader) == [(OP_BINARY, payload)]

    def test_unmasked_client_frame_rejected(self):
        reader = FrameReader()
        reader.feed(encode_frame(OP_TEXT, b"nope"))  # server-style, unmasked
        with pytest.raises(WSProtocolError):
            _drain(reader)

    def test_rsv_bits_rejected(self):
        reader = FrameReader()
        reader.feed(_mask_frame(OP_TEXT, b"x", rsv=0b100))
        with pytest.raises(WSProtocolError):
            _drain(reader)

    def test_unknown_opcode_rejected(self):
        reader = FrameReader()
        frame = bytearray(_mask_frame(OP_TEXT, b"x"))
        frame[0] = 0x80 | 0x3  # reserved non-control opcode
        reader.feed(bytes(frame))
        with pytest.raises(WSProtocolError):
            _drain(reader)

    def test_continuation_without_start_rejected(self):
        reader = FrameReader()
        reader.feed(_mask_frame(OP_CONT, b"x", fin=True))
        with pytest.raises(WSProtocolError):
            _drain(reader)

    def test_new_data_frame_during_fragmentation_rejected(self):
        reader = FrameReader()
        reader.feed(_mask_frame(OP_TEXT, b"a", fin=False))
        reader.feed(_mask_frame(OP_TEXT, b"b", fin=True))
        with pytest.raises(WSProtocolError):
            _drain(reader)

    def test_fragmented_control_frame_rejected(self):
        reader = FrameReader()
        reader.feed(_mask_frame(OP_PING, b"x", fin=False))
        with pytest.raises(WSProtocolError):
            _drain(reader)

    def test_oversized_frame_rejected(self):
        reader = FrameReader(max_message=64)
        reader.feed(_mask_frame(OP_BINARY, b"y" * 65))
        with pytest.raises(WSProtocolError):
            _drain(reader)

    def test_server_frame_parsing_when_mask_not_required(self):
        reader = FrameReader(require_mask=False)
        reader.feed(encode_frame(OP_TEXT, b"srv"))
        assert _drain(reader) == [(OP_TEXT, b"srv")]

    def test_many_frames_in_one_feed(self):
        reader = FrameReader()
        blob = b"".join(_mask_frame(OP_TEXT, f"m{i}".encode()) for i in range(5))
        reader.feed(blob)
        assert [p for _, p in _drain(reader)] == [b"m0", b"m1", b"m2", b"m3", b"m4"]
