# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Chat attachments are compressed BEFORE they go on the wire.

An iPhone photo used to be uploaded as-is: the FILE path base64'd the original
file bytes (~5.8 MB for a 12 MP JPEG) and the BLEND_DATA path built a
full-resolution RGBA PNG (~47 MB base64) that overshot the backend's 30 MB raw
ceiling — so the backend's own compression pass never ran and the attachment
was dropped before the agent ever saw it.

The byte-level compressor is pure PIL, so these are real functional tests; the
operator wiring is pinned at source level because ``bpy`` is a MagicMock here
(see the root ``conftest.py``).
"""

import base64
import io
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"


def _load_compressor():
    """Load by path: importing through the package pulls in the auth module
    (and its ``keyring`` dependency), which this suite deliberately lacks."""
    import importlib.util

    path = CHAT / "core/attachment_compression.py"
    spec = importlib.util.spec_from_file_location("attachment_compression_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_compressor = _load_compressor()
CHAT_ATTACHMENT_MAX_EDGE = _compressor.CHAT_ATTACHMENT_MAX_EDGE
MAX_DECODE_PIXELS = _compressor.MAX_DECODE_PIXELS
compress_file_for_chat = _compressor.compress_file_for_chat
compress_image_bytes = _compressor.compress_image_bytes


def _photo_bytes(size=(4032, 3024), fmt="JPEG", mode="RGB", **save_kw) -> bytes:
    """A photographic-looking image — flat colour would compress so well that
    the shrink guard could mask a broken resize."""
    import os

    noise = Image.frombytes("RGB", (64, 64), os.urandom(64 * 64 * 3))
    img = noise.resize(size, Image.BILINEAR).convert(mode)
    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_kw)
    return buf.getvalue()


def _decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


class TestCompressImageBytes:
    def test_camera_photo_is_downscaled_and_reencoded(self):
        raw = _photo_bytes(quality=92)
        result = compress_image_bytes(raw)

        assert result is not None
        data, mime = result
        assert mime == "image/jpeg"
        assert max(_decode(data).size) == CHAT_ATTACHMENT_MAX_EDGE
        # The whole point: a few hundred KB on the wire instead of megabytes.
        # (A real 12 MP camera JPEG is ~4 MB and lands around 200 KB here.)
        assert len(data) < 500 * 1024
        assert len(data) < len(raw) / 4

    def test_aspect_ratio_is_preserved(self):
        result = compress_image_bytes(_photo_bytes(size=(4032, 3024), quality=92))
        assert result is not None
        w, h = _decode(result[0]).size
        assert (w, h) == (CHAT_ATTACHMENT_MAX_EDGE, round(CHAT_ATTACHMENT_MAX_EDGE * 3024 / 4032))

    def test_small_image_below_the_cap_is_not_upscaled(self):
        raw = _photo_bytes(size=(800, 600), fmt="PNG")
        result = compress_image_bytes(raw)
        assert result is not None  # PNG -> JPEG still wins on a photo
        assert _decode(result[0]).size == (800, 600)

    def test_already_small_jpeg_is_left_alone(self):
        """No gain -> None, meaning 'upload the original'. Re-encoding a small
        JPEG would only lose quality for nothing."""
        raw = _photo_bytes(size=(320, 240), quality=60)
        assert compress_image_bytes(raw) is None

    def test_exif_rotated_photo_is_uprighted(self):
        """iPhone photos are stored landscape with an orientation tag; without
        the transpose the model sees them sideways."""
        import os

        noise = Image.frombytes("RGB", (64, 64), os.urandom(64 * 64 * 3))
        img = noise.resize((4000, 3000), Image.BILINEAR)
        exif = img.getexif()
        exif[0x0112] = 6  # Orientation: rotate 90 CW -> portrait
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92, exif=exif)

        result = compress_image_bytes(buf.getvalue())
        assert result is not None
        w, h = _decode(result[0]).size
        assert h > w, "EXIF orientation was not applied"
        # EXIF is dropped by the re-encode, so the backend cannot rotate again.
        assert not _decode(result[0]).getexif().get(0x0112)

    def test_transparency_is_flattened_onto_white(self):
        """PIL's bare convert('RGB') composites onto BLACK, which turns a
        dark-foreground cutout into a near-black frame."""
        import os

        img = Image.new("RGBA", (2000, 2000), (0, 0, 0, 0))
        noise = Image.frombytes("RGB", (600, 600), os.urandom(600 * 600 * 3))
        img.paste(noise.convert("RGBA"), (700, 700))
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        result = compress_image_bytes(buf.getvalue())
        assert result is not None
        r, g, b = _decode(result[0]).convert("RGB").getpixel((5, 5))
        assert r > 200 and g > 200 and b > 200

    def test_marginal_gain_is_not_worth_a_second_lossy_pass(self):
        """Re-encoding a JPEG that is already the right size shaves a rounding
        error off the payload and costs a whole lossy generation."""
        raw = _photo_bytes(size=(1568, 1176), quality=85)
        assert compress_image_bytes(raw) is None

    def test_unsupported_format_is_converted_regardless_of_size(self):
        """Anthropic accepts jpeg/png/gif/webp only — a .bmp or .tiff
        attachment was declared as image/bmp and rejected by the provider.
        Conversion must not be skipped just because the bytes barely shrank."""
        raw = _photo_bytes(size=(200, 150), fmt="TIFF")
        result = compress_image_bytes(raw, original_size=1)
        assert result is not None and result[1] == "image/jpeg"

    def test_undecodable_bytes_fall_back_to_the_original(self):
        assert compress_image_bytes(b"not an image at all") is None
        assert compress_image_bytes(b"") is None

    def test_decode_bomb_is_refused_before_any_pixels_are_read(self):
        """A tiny PNG can declare a gigapixel canvas. The pixel cap, not the
        byte count, is what bounds decoder memory."""
        side = int(MAX_DECODE_PIXELS ** 0.5) + 5000
        buf = io.BytesIO()
        Image.new("L", (side, side)).save(buf, format="PNG")
        assert side * side > MAX_DECODE_PIXELS
        assert compress_image_bytes(buf.getvalue()) is None

    def test_budget_argument_measures_gain_against_the_alternative(self):
        """The BLEND_DATA pixel path compares against the PNG it would
        otherwise have uploaded, not against its own source buffer."""
        raw = _photo_bytes(size=(320, 240), quality=60)
        assert compress_image_bytes(raw) is None
        assert compress_image_bytes(raw, original_size=50_000_000) is not None


class TestCompressFileForChat:
    def test_reads_and_compresses_a_file(self, tmp_path):
        path = tmp_path / "IMG_4021.JPG"
        path.write_bytes(_photo_bytes(quality=92))

        result = compress_file_for_chat(str(path))
        assert result is not None
        data, mime = result
        assert mime == "image/jpeg"
        assert max(_decode(data).size) == CHAT_ATTACHMENT_MAX_EDGE

    def test_missing_file_is_not_fatal(self, tmp_path):
        assert compress_file_for_chat(str(tmp_path / "nope.jpg")) is None


class TestUploadPathContract:
    """Source-level pins: the send path must use the compressing encoder."""

    def test_chat_ops_encodes_through_the_compressing_path(self):
        source = (CHAT / "ui/operators/chat_ops.py").read_text(encoding="utf-8")
        assert "encode_attachment_for_upload" in source
        assert "image_to_base64" not in source, (
            "chat_ops must not encode attachments without compressing them"
        )

    def test_mime_comes_from_the_encoder_not_the_extension(self):
        """The bytes on the wire are JPEG after compression, so a mime guessed
        from the source extension would mis-declare them — Anthropic rejects a
        declared-vs-actual mismatch with a 400."""
        source = (CHAT / "ui/operators/chat_ops.py").read_text(encoding="utf-8")
        assert "mime_map" not in source
        assert "b64, mime_type = encoded" in source

    def test_one_slow_attachment_does_not_drop_the_others(self):
        source = (CHAT / "ui/operators/chat_ops.py").read_text(encoding="utf-8")
        block = source[source.index("for idx, future in enumerate(encoding_futures)"):]
        block = block[: block.index("total_encode_time")]
        assert "encoded_attachments = []" not in block, (
            "a per-image failure must skip that image, not wipe the whole set"
        )
        assert block.count("continue") >= 2

    def test_blend_data_stays_on_the_main_thread(self):
        source = (CHAT / "ui/operators/chat_ops.py").read_text(encoding="utf-8")
        submit = source[source.index("executor.submit("):]
        submit = submit[: submit.index("encoding_futures.append(future)")]
        assert "att.image_source" in submit
        assert "'FILE'" in source[: source.index("executor.submit(")][-400:]

    def test_client_and_backend_compression_targets_are_documented_together(self):
        """Both halves target the same edge/quality so the backend's pass is a
        no-op on our bytes. A drift here silently doubles the re-encode."""
        source = (CHAT / "core/attachment_compression.py").read_text(encoding="utf-8")
        assert "CHAT_ATTACHMENT_MAX_EDGE = 1568" in source
        assert "CHAT_ATTACHMENT_JPEG_QUALITY = 85" in source
        assert "IMAGE_MAX_EDGE_PX" in source and "IMAGE_JPEG_QUALITY" in source

